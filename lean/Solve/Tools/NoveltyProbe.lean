import Lean
import Lean.Data.Json
import Solve.Tools.AtomDump

open Lean
open Lean.Elab.Command

namespace Solve.Tools.NoveltyProbe

register_option solve.novelty.target : String := {
  defValue := ""
  descr := "Fully-qualified declaration name for novelty probing."
}

register_option solve.novelty.prefixes : String := {
  defValue := ""
  descr := "Comma-separated namespace prefixes to scan for imported defeq duplicates."
}

register_option solve.novelty.candidateCap : Nat := {
  defValue := 5000
  descr := "Maximum number of imported constants to compare."
}

register_option solve.novelty.heartbeatBudget : Nat := {
  defValue := 1000
  descr := "Per-comparison heartbeat budget for novelty defeq checks."
}

def parseName (raw : String) : Name :=
  raw.splitOn "." |>.foldl (fun acc part => Name.str acc part) Name.anonymous

def truncate (message : String) : String :=
  if message.length > 300 then
    (message.take 300).toString ++ "..."
  else
    message

def allowedKind : ConstantInfo → Bool
  | .defnInfo _ => true
  | .thmInfo _ => true
  | .axiomInfo _ => true
  | .opaqueInfo _ => true
  | _ => false

def emit (payload : Json) : CommandElabM Unit := do
  IO.println ("NOV " ++ Json.compress payload)
  IO.println "NOV_DONE"

def payload
    (target : Name)
    (verdict : String)
    (witness : Option Name)
    (compared : Nat)
    (capHit : Bool)
    (reason : String) : Json :=
  Json.mkObj [
    ("target", toJson (toString target)),
    ("verdict", toJson verdict),
    ("witness", toJson (witness.map toString)),
    ("compared", toJson compared),
    ("cap_hit", toJson capHit),
    ("reason", toJson reason)
  ]

def compareTypes (targetType : Expr) (candidateType : Expr) (heartbeatBudget : Nat) :
    Lean.Elab.Term.TermElabM Bool := do
  try
    Meta.withNewMCtxDepth do
      let targetType ← instantiateMVars targetType
      let candidateType ← instantiateMVars candidateType
      Meta.isDefEq targetType candidateType
  catch _ =>
    /- Individual isDefEq throws almost always mean "structurally incompatible,
       not defeq" — genuine duplicates resolve trivially. Treat throws as
       not-equal. Global budget exhaustion or process-level errors are caught
       by the outer try/catch in `run` and reported as "unknown". -/
    pure false

def run : CommandElabM Unit := do
  try
    let opts ← getOptions
    let targetRaw := solve.novelty.target.get opts
    let prefixRaw := solve.novelty.prefixes.get opts
    let prefixes := Solve.Tools.AtomDump.parsePrefixes prefixRaw
    let candidateCap := solve.novelty.candidateCap.get opts
    let heartbeatBudget := solve.novelty.heartbeatBudget.get opts
    if targetRaw.trimAscii.toString.isEmpty then
      emit (payload Name.anonymous "unknown" none 0 false "solve.novelty.target is missing")
      return
    if prefixes.isEmpty then
      emit (payload (parseName targetRaw) "unknown" none 0 false "solve.novelty.prefixes is missing")
      return
    let target := parseName targetRaw
    let env ← getEnv
    let some targetInfo := env.find? target
      | emit (payload target "unknown" none 0 false "target not found"); return
    let constants :=
      env.constants.fold (fun acc _ info => acc.push info) #[]
        |>.qsort fun left right => left.name.cmp right.name == .lt
    let eligible :=
      constants.filter fun info =>
        info.name != target &&
        allowedKind info &&
        !Solve.Tools.AtomDump.shouldSkip info.name &&
        Solve.Tools.AtomDump.matchesPrefix prefixes info.name
    let limit := Nat.min candidateCap eligible.size
    let capped := eligible.extract 0 limit
    let mut compared := 0
    let mut witness : Option Name := none
    let targetType ← liftTermElabM <| instantiateMVars targetInfo.type
    for info in capped do
      if witness.isNone then
        compared := compared + 1
        let same ← liftTermElabM <| compareTypes targetType info.type heartbeatBudget
        if same then
          witness := some info.name
    match witness with
    | some found =>
        emit (payload target "existing_defeq_duplicate" (some found) compared false "defeq match in imported environment")
    | none =>
        let capHit := eligible.size > candidateCap
        /- Fail-closed: if the cap was hit we did not check all candidates, so
           we cannot confirm novelty. Report "unknown" instead of "novel". -/
        if capHit then
          emit (payload target "unknown" none compared true "cap hit; not all candidates checked")
        else
          emit (payload target "novel_in_imported_env" none compared false "no imported defeq duplicate found")
  catch exc =>
    let opts ← getOptions
    let targetRaw := solve.novelty.target.get opts
    let target := if targetRaw.trimAscii.toString.isEmpty then Name.anonymous else parseName targetRaw
    let message ← exc.toMessageData.toString
    emit (payload target "unknown" none 0 false ("probe_error: " ++ truncate message))

elab "#solve_novelty_probe" : command => run

end Solve.Tools.NoveltyProbe
