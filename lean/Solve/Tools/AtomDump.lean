import Lean
import Lean.Data.Json
import Lean.Util.CollectAxioms

open Lean
open Lean.Elab.Command

namespace Solve.Tools.AtomDump

register_option solve.atom.prefixes : String := {
  defValue := ""
  descr := "Comma-separated namespace prefixes for seed atom enumeration."
}

register_option solve.atom.seedLimit : Nat := {
  defValue := 100
  descr := "Maximum number of atom records to emit."
}

def parsePrefixes (raw : String) : Array String :=
  (raw.splitOn "," |>.filterMap fun part =>
    let pref := part.trimAscii.toString
    if pref.isEmpty then none else some pref).toArray

def matchesPrefix (prefixes : Array String) (name : Name) : Bool :=
  let rendered := toString name
  prefixes.any fun pref => rendered == pref || rendered.startsWith (pref ++ ".")

def kindOf : ConstantInfo → String
  | .defnInfo _ => "def"
  | .thmInfo _ => "theorem"
  | .axiomInfo _ => "axiom"
  | .ctorInfo _ => "ctor"
  | .inductInfo _ => "inductive"
  | .opaqueInfo _ => "opaque"
  | .quotInfo _ => "quot"
  | .recInfo _ => "other"

def moduleFor? (env : Environment) (name : Name) : Option String := do
  let idx ← env.getModuleIdxFor? name
  let moduleName ← env.header.moduleNames[idx]?
  some (toString moduleName)

def collectAxioms? (name : Name) : CommandElabM (Option (Array String)) := do
  try
    let axioms ← Lean.collectAxioms name
    pure (some (axioms.map fun ax => toString ax))
  catch _ =>
    pure none

def summarizeType (type : Expr) : Lean.Elab.Term.TermElabM (String × String × Option Nat) := do
  let type ← instantiateMVars type
  let rendered ← Meta.ppExpr type
  -- Hashes the instantiated declaration type without unfolding or reduction.
  -- binder_count/arity below are computed from Lean's reduced forall telescope.
  let typeHash := toString (hash type)
  let binderCount? ←
    try
      withTheReader Core.Context (fun ctx => { ctx with maxHeartbeats := 0 }) do
        let count ← Meta.forallTelescopeReducing type (cleanupAnnotations := true) (whnfType := true) fun xs _ =>
          pure xs.size
        pure (some count)
    catch _ =>
      pure none
  pure (rendered.pretty, typeHash, binderCount?)

def jsonRecord (env : Environment) (info : ConstantInfo) : CommandElabM Json := do
  let name := info.name
  let (typePp, typeHash, binderCount?) ← liftTermElabM <| summarizeType info.type
  let axioms? ← collectAxioms? name
  let module? := moduleFor? env name
  pure <| Json.mkObj [
    ("name", toJson (toString name)),
    ("kind", toJson (kindOf info)),
    ("type_pp", toJson typePp),
    ("type_hash", toJson typeHash),
    ("binder_count", toJson binderCount?),
    ("arity", toJson binderCount?),
    ("module", toJson module?),
    ("axioms", toJson axioms?)
  ]

def shouldSkip (name : Name) : Bool :=
  name.isInternal || isPrivateName name

def run : CommandElabM Unit := do
  let opts ← getOptions
  let prefixes := parsePrefixes (solve.atom.prefixes.get opts)
  let seedLimit := solve.atom.seedLimit.get opts
  if prefixes.isEmpty then
    throwError "solve.atom.prefixes must contain at least one namespace prefix"
  let env ← getEnv
  let constants :=
    env.constants.fold (fun acc _ info => acc.push info) #[]
      |>.qsort fun left right => left.name.quickCmp right.name == .lt
  let mut emitted := 0
  for info in constants do
    if emitted < seedLimit then
      let name := info.name
      if !shouldSkip name && matchesPrefix prefixes name then
        let record ← jsonRecord env info
        IO.println ("ATOM " ++ Json.compress record)
        emitted := emitted + 1
  IO.println s!"ATOM_DONE count={emitted}"

elab "#solve_atom_dump" : command => run

end Solve.Tools.AtomDump
