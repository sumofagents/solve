import Lean
import Lean.Data.Json

open Lean
open Lean.Elab.Command

namespace Solve.Tools.ProofSizeProbe

register_option solve.proofsize.target : String := {
  defValue := ""
  descr := "Fully-qualified declaration name whose elaborated value's expression size will be measured."
}

register_option solve.proofsize.requiredConst : String := {
  defValue := ""
  descr := "Optional fully-qualified constant name expected to appear in the proof body."
}

def parseName (raw : String) : Name :=
  raw.splitOn "." |>.foldl (fun acc part => Name.str acc part) Name.anonymous

partial def stripMetadata : Expr → Expr
  | .mdata _ body => stripMetadata body
  | expr => expr

def truncate (message : String) : String :=
  if message.length > 300 then
    (message.take 300).toString ++ "..."
  else
    message

/--
Count the number of Expr nodes after stripping outer metadata at each recursive step.
Every constructor counts as 1; we recurse into all subterms. Metadata wrappers are
skipped (not counted) by stripping at entry.
-/
partial def termSize (expr : Expr) : Nat :=
  let expr := stripMetadata expr
  match expr with
  | .app fn arg => 1 + termSize fn + termSize arg
  | .lam _ domain body _ => 1 + termSize domain + termSize body
  | .forallE _ domain body _ => 1 + termSize domain + termSize body
  | .letE _ type value body _ => 1 + termSize type + termSize value + termSize body
  | .proj _ _ struct => 1 + termSize struct
  | .mdata _ body => 1 + termSize body
  | .const _ _ => 1
  | .fvar _ => 1
  | .bvar _ => 1
  | .mvar _ => 1
  | .sort _ => 1
  | .lit _ => 1

/--
Decide whether `needed` appears as a `.const` head somewhere inside `expr` after
metadata stripping.
-/
partial def usesConst (expr : Expr) (needed : Name) : Bool :=
  let expr := stripMetadata expr
  match expr with
  | .const name _ => name == needed
  | .app fn arg => usesConst fn needed || usesConst arg needed
  | .lam _ domain body _ => usesConst domain needed || usesConst body needed
  | .forallE _ domain body _ => usesConst domain needed || usesConst body needed
  | .letE _ type value body _ =>
      usesConst type needed || usesConst value needed || usesConst body needed
  | .proj _ _ struct => usesConst struct needed
  | .mdata _ body => usesConst body needed
  | _ => false

def emit (payload : Json) : CommandElabM Unit := do
  IO.println ("PROOFSIZE " ++ Json.compress payload)
  IO.println "PROOFSIZE_DONE"

def payloadJson
    (target : String)
    (verdict : String)
    (termSizeOpt : Option Nat)
    (requiredConst : Option String)
    (usedRequiredConst : Option Bool)
    (reason : String) : Json :=
  Json.mkObj [
    ("target", toJson target),
    ("verdict", toJson verdict),
    ("term_size", toJson termSizeOpt),
    ("required_const", toJson requiredConst),
    ("used_required_const", toJson usedRequiredConst),
    ("reason", toJson reason)
  ]

def extractValue? : ConstantInfo → Option Expr
  | .thmInfo info => some info.value
  | .defnInfo info => some info.value
  | .opaqueInfo info => some info.value
  | _ => none

def inspect (targetRaw : String) : CommandElabM Unit := do
  let opts ← getOptions
  let targetTrimmed := targetRaw.trimAscii.toString
  let requiredRaw := (solve.proofsize.requiredConst.get opts).trimAscii.toString
  let requiredOpt : Option String :=
    if requiredRaw.isEmpty then none else some requiredRaw
  if targetTrimmed.isEmpty then
    emit (payloadJson "" "unknown" none requiredOpt none "solve.proofsize.target is missing")
    return
  let env ← getEnv
  let target := parseName targetTrimmed
  let some info := env.find? target
    | emit (payloadJson targetTrimmed "unknown" none requiredOpt none "target not found"); return
  let some rawValue := extractValue? info
    | emit (payloadJson targetTrimmed "unknown" none requiredOpt none
        "unsupported constant kind (no value to measure)"); return
  let resultPair ← liftTermElabM do
    try
      let v ← instantiateMVars rawValue
      let v := stripMetadata v
      let size := termSize v
      let usedOpt : Option Bool :=
        match requiredOpt with
        | some requiredName =>
            some (usesConst v (parseName requiredName))
        | none => none
      pure <| Except.ok (size, usedOpt)
    catch exc =>
      let msg ← exc.toMessageData.toString
      pure <| Except.error msg
  match resultPair with
  | .error reason =>
      emit (payloadJson targetTrimmed "unknown" none requiredOpt none
        ("probe_error: " ++ truncate reason))
  | .ok (size, usedOpt) =>
      emit (payloadJson targetTrimmed "ok" (some size) requiredOpt usedOpt "")

def runTargetRaw (targetRaw : String) : CommandElabM Unit := do
  try
    inspect targetRaw
  catch exc =>
    let message ← exc.toMessageData.toString
    let opts ← getOptions
    let requiredRaw := (solve.proofsize.requiredConst.get opts).trimAscii.toString
    let requiredOpt : Option String :=
      if requiredRaw.isEmpty then none else some requiredRaw
    emit (payloadJson targetRaw "unknown" none requiredOpt none
      ("probe_error: " ++ truncate message))

elab "#solve_proof_size_probe " target:ident : command => do
  runTargetRaw (toString target.getId)

elab "#solve_proof_size_probe" : command => do
  let raw := solve.proofsize.target.get (← getOptions)
  runTargetRaw raw

end Solve.Tools.ProofSizeProbe
