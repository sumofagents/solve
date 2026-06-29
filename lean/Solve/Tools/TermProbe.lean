import Lean
import Lean.Data.Json
import Std.Data.HashSet

open Lean
open Lean.Elab.Command

namespace Solve.Tools.TermProbe

register_option solve.probe.target : String := {
  defValue := ""
  descr := "Fully-qualified declaration name for structural packaging probing."
}

def parseName (raw : String) : Name :=
  raw.splitOn "." |>.foldl (fun acc part => Name.str acc part) Name.anonymous

partial def stripMetadata : Expr → Expr
  | .mdata _ body => stripMetadata body
  | expr => expr

def structuralHeads : Std.HashSet Name :=
  Id.run do
    let mut heads := (Std.HashSet.emptyWithCapacity : Std.HashSet Name)
    heads := heads.insert `And.intro
    heads := heads.insert `Or.inl
    heads := heads.insert `Or.inr
    heads := heads.insert `Eq.refl
    heads := heads.insert `Prod.mk
    heads := heads.insert `Iff.intro
    heads := heads.insert `Sigma.mk
    heads := heads.insert `PSigma.mk
    heads := heads.insert `Subtype.mk
    heads := heads.insert `Exists.intro
    heads

def isStructuralHead (name : Name) : Bool :=
  structuralHeads.contains name

def trailingUserArgCount : Name → Nat
  | `And.intro => 2
  | `Or.inl => 1
  | `Or.inr => 1
  | `Eq.refl => 1
  | `Prod.mk => 2
  | `Iff.intro => 2
  | `Sigma.mk => 2
  | `PSigma.mk => 2
  | `Subtype.mk => 2
  | `Exists.intro => 2
  | _ => 0

def trailingUserArgs (head : Name) (args : Array Expr) : Array Expr :=
  let count := trailingUserArgCount head
  let start := if args.size > count then args.size - count else 0
  args.extract start args.size

def isGeneratedRunControl (name : Name) : Bool :=
  let rendered := toString name
  rendered == "Solve.Generated.RunControl" ||
    rendered.startsWith "Solve.Generated.RunControl."

def truncate (message : String) : String :=
  if message.length > 300 then
    (message.take 300).toString ++ "..."
  else
    message

def argJson (env : Environment) (arg : Expr) : Json :=
  let fn := stripMetadata arg |>.getAppFn
  match fn with
  | .const name _ =>
      let imported := env.contains name && !isGeneratedRunControl name
      Json.mkObj [
        ("kind", toJson "const"),
        ("name", toJson (some (toString name) : Option String)),
        ("imported", toJson (some imported : Option Bool))
      ]
  | .fvar fvarId =>
      Json.mkObj [
        ("kind", toJson "fvar"),
        ("name", toJson (some (toString fvarId.name) : Option String)),
        ("imported", toJson (none : Option Bool))
      ]
  | .lit _ =>
      Json.mkObj [
        ("kind", toJson "literal"),
        ("name", toJson (none : Option String)),
        ("imported", toJson (none : Option Bool))
      ]
  | _ =>
      Json.mkObj [
        ("kind", toJson "other"),
        ("name", toJson (none : Option String)),
        ("imported", toJson (none : Option Bool))
      ]

def isImportedAtom (env : Environment) (arg : Expr) : Bool :=
  match stripMetadata arg with
  | .const name _ => env.contains name && !isGeneratedRunControl name
  | _ => false

def getAppFnStripped (expr : Expr) : Name :=
  match stripMetadata expr |>.getAppFn with
  | .const name _ => name
  | _ => Name.anonymous

def isImportedAtomForFailure (env : Environment) (arg : Expr) : Option String :=
  match stripMetadata arg with
  | .const name _ =>
      if env.contains name && !isGeneratedRunControl name then
        none
      else
        some (s!"non-imported constant {toString name}")
  | .app fn _ =>
      some (s!"non-atom application {toString (getAppFnStripped fn)}")
  | .fvar fvarId => some (s!"non-imported free variable {toString fvarId.name}")
  | .lit _ => some "non-imported literal argument"
  | _ => some "non-imported non-constant argument"

def emit (payload : Json) : CommandElabM Unit := do
  IO.println ("STRUCT " ++ Json.compress payload)
  IO.println "STRUCT_DONE"

def errorPayload (target : Name) (reason : String) : Json :=
  Json.mkObj [
    ("target", toJson (toString target)),
    ("head", toJson (none : Option String)),
    ("args", Json.arr #[]),
    ("verdict", toJson "error"),
    ("reason", toJson reason)
  ]

def inspect (target : Name) : CommandElabM Json := do
  let env ← getEnv
  let some info := env.find? target
    | return errorPayload target "target not found"
  let some value := info.value?
    | return errorPayload target "target has no value"
  liftTermElabM do
    let value ← instantiateMVars value
    let value := stripMetadata value
    let headExpr := value.getAppFn
    let head? :=
      match headExpr with
      | .const name _ => some name
      | _ => none
    let rawArgs := value.getAppArgs
    match head? with
    | none =>
        pure <| Json.mkObj [
          ("target", toJson (toString target)),
          ("head", toJson (none : Option String)),
          ("args", Json.arr #[]),
          ("verdict", toJson "non_structural"),
          ("reason", toJson "non-structural head")
        ]
    | some head =>
        if !isStructuralHead head then
          pure <| Json.mkObj [
            ("target", toJson (toString target)),
            ("head", toJson (some (toString head) : Option String)),
            ("args", Json.arr #[]),
            ("verdict", toJson "non_structural"),
            ("reason", toJson "non-structural head")
          ]
        else
          let args := trailingUserArgs head rawArgs
          let argRecords := args.map (argJson env)
          let mut failing : Option String := none
          for arg in args do
            if failing.isNone then
              failing := isImportedAtomForFailure env arg
          let verdict := if failing.isSome then "non_structural" else "structural"
          let reason :=
            match failing with
            | some msg => msg
            | none => toString head ++ " of imported atoms"
          pure <| Json.mkObj [
            ("target", toJson (toString target)),
            ("head", toJson (some (toString head) : Option String)),
            ("args", Json.arr argRecords),
            ("verdict", toJson verdict),
            ("reason", toJson reason)
          ]

def runTarget (target : Name) : CommandElabM Unit := do
  try
    let payload ← inspect target
    emit payload
  catch exc =>
    let message ← exc.toMessageData.toString
    emit (errorPayload target ("probe_error: " ++ truncate message))

elab "#solve_structural_probe " target:ident : command => do
  runTarget target.getId

elab "#solve_structural_probe" : command => do
  let raw := solve.probe.target.get (← getOptions)
  if raw.trimAscii.isEmpty then
    emit (errorPayload Name.anonymous "probe_error: solve.probe.target is missing")
  else
    runTarget (parseName raw)

end Solve.Tools.TermProbe
