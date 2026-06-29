import Lean
import Lean.Data.Json
import Std.Data.HashSet

open Lean
open Lean.Elab.Command

namespace Solve.Tools.UsageProbe

register_option solve.usage.target : String := {
  defValue := ""
  descr := "Fully-qualified declaration name for downstream usage probing."
}

register_option solve.usage.promoted : String := {
  defValue := ""
  descr := "Comma-separated promoted constant names to intersect with proof-term constants."
}

register_option solve.usage.maxConstants : Nat := {
  defValue := 10000
  descr := "Maximum number of distinct constants collected before returning unknown."
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

def parsePromotedNames (raw : String) : Std.HashSet Name :=
  Id.run do
    let mut names := (Std.HashSet.emptyWithCapacity : Std.HashSet Name)
    for part in raw.splitOn "," do
      let trimmed := part.trimAscii.toString
      if !trimmed.isEmpty then
        names := names.insert (parseName trimmed)
    names

def emit (payload : Json) : CommandElabM Unit := do
  IO.println ("USAGE " ++ Json.compress payload)
  IO.println "USAGE_DONE"

def payload (target : String) (used : Array Name) (unknown : Bool) (reason : String) : Json :=
  Json.mkObj [
    ("target", toJson target),
    ("used_promoted", Json.arr (used.map (fun name => toJson (toString name)))),
    ("unknown", toJson unknown),
    ("reason", toJson reason)
  ]

partial def collectConstants (expr : Expr) (maxConstants : Nat) (seen : Std.HashSet Name) :
    Except String (Std.HashSet Name) := do
  let expr := stripMetadata expr
  match expr with
  | .const name _ =>
      let seen := seen.insert name
      if seen.size > maxConstants then
        throw "constant cap hit"
      else
        pure seen
  | .app fn arg =>
      let seen ← collectConstants fn maxConstants seen
      collectConstants arg maxConstants seen
  | .lam _ domain body _ =>
      let seen ← collectConstants domain maxConstants seen
      collectConstants body maxConstants seen
  | .forallE _ domain body _ =>
      let seen ← collectConstants domain maxConstants seen
      collectConstants body maxConstants seen
  | .letE _ type value body _ =>
      let seen ← collectConstants type maxConstants seen
      let seen ← collectConstants value maxConstants seen
      collectConstants body maxConstants seen
  | .mdata _ body =>
      collectConstants body maxConstants seen
  | .proj _ _ struct =>
      collectConstants struct maxConstants seen
  | .sort _ => pure seen
  | .lit _ => pure seen
  | .bvar _ => pure seen
  | .fvar _ => pure seen
  | .mvar _ => pure seen

def usedPromoted (seen : Std.HashSet Name) (promoted : Std.HashSet Name) : Array Name :=
  (seen.toArray.filter (fun name => promoted.contains name)).qsort
    (fun left right => left.cmp right == .lt)

def inspect (targetRaw : String) : CommandElabM Unit := do
  let opts ← getOptions
  let targetTrimmed := targetRaw.trimAscii.toString
  if targetTrimmed.isEmpty then
    emit (payload "" #[] true "solve.usage.target is missing")
    return
  let promoted := parsePromotedNames (solve.usage.promoted.get opts)
  if promoted.size == 0 then
    emit (payload targetTrimmed #[] false "")
    return
  let target := parseName targetTrimmed
  let env ← getEnv
  let some info := env.find? target
    | emit (payload targetTrimmed #[] true "target not found"); return
  let some value := info.value?
    | emit (payload targetTrimmed #[] true "target has no value"); return
  let maxConstants := solve.usage.maxConstants.get opts
  let collected ← liftTermElabM do
    let value ← instantiateMVars value
    pure <| collectConstants value maxConstants (Std.HashSet.emptyWithCapacity : Std.HashSet Name)
  match collected with
  | .error reason =>
      emit (payload targetTrimmed #[] true reason)
  | .ok seen =>
      let used := usedPromoted seen promoted
      emit (payload targetTrimmed used false "")

def runTargetRaw (targetRaw : String) : CommandElabM Unit := do
  try
    inspect targetRaw
  catch exc =>
    let message ← exc.toMessageData.toString
    emit (payload targetRaw #[] true ("probe_error: " ++ truncate message))

elab "#solve_usage_probe " target:ident : command => do
  runTargetRaw (toString target.getId)

elab "#solve_usage_probe" : command => do
  let raw := solve.usage.target.get (← getOptions)
  runTargetRaw raw

end Solve.Tools.UsageProbe
