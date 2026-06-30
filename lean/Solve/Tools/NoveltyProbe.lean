import Lean
import Lean.Data.Json
import Lean.Meta.DiscrTree
import Solve.Tools.AtomDump

open Lean
open Lean.Elab.Command

namespace Solve.Tools.NoveltyProbe

register_option solve.novelty.target : String := {
  defValue := ""
  descr := "Fully-qualified declaration name for novelty probing."
}

register_option solve.novelty.targetsFile : String := {
  defValue := ""
  descr := "Path to JSONL target records of the form {\"name\":\"...\"}."
}

register_option solve.novelty.prefixes : String := {
  defValue := ""
  descr := "Comma-separated namespace prefixes to scan for imported defeq duplicates."
}

register_option solve.novelty.verifyMode : String := {
  defValue := "brute"
  descr := "Novelty verification mode: brute (exhaustive, sound) or discrtree (fast pre-filter, may miss symmetric defeq)."
}

register_option solve.novelty.globalScope : Bool := {
  defValue := false
  descr := "When true, scan declarations owned by Mathlib modules instead of namespace prefixes."
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

def isMathlibModule (moduleName : String) : Bool :=
  moduleName == "Mathlib" || moduleName.startsWith "Mathlib."

def ownedByMathlib (env : Environment) (name : Name) : Bool :=
  match Solve.Tools.AtomDump.moduleFor? env name with
  | some moduleName => isMathlibModule moduleName
  | none => false

def emitNov (payload : Json) : CommandElabM Unit := do
  IO.println ("NOV " ++ Json.compress payload)

def emitDone : CommandElabM Unit := do
  IO.println "NOV_DONE"

def payload
    (target : Name)
    (verdict : String)
    (witness : Option Name)
    (compared : Nat)
    (capHit : Bool)
    (reason : String)
    (bucketSize : Option Nat := none)
    (indexSize : Option Nat := none)
    (mode : Option String := none) : Json :=
  Json.mkObj [
    ("target", toJson (toString target)),
    ("verdict", toJson verdict),
    ("witness", toJson (witness.map toString)),
    ("compared", toJson compared),
    ("cap_hit", toJson capHit),
    ("reason", toJson reason),
    ("bucket_size", toJson bucketSize),
    ("index_size", toJson indexSize),
    ("mode", toJson mode)
  ]

/- Tri-state comparison result: `some true` = defeq, `some false` = definitely
   not defeq, `none` = uncertain (exception / heartbeat timeout). The caller
   must propagate `none` as `unknown` to preserve fail-closed semantics. -/
def compareTypes? (targetType : Expr) (candidateType : Expr) (heartbeatBudget : Nat) :
    Lean.Elab.Term.TermElabM (Option Bool) := do
  try
    withTheReader Core.Context (fun ctx => { ctx with maxHeartbeats := heartbeatBudget }) do
      Meta.withNewMCtxDepth do
        let targetType ← instantiateMVars targetType
        let candidateType ← instantiateMVars candidateType
        pure (some (← Meta.isDefEq targetType candidateType))
  catch _ =>
    /- Exception means uncertain — could be heartbeat timeout, out-of-memory,
       or an internal Lean error. Return none so the caller can fail-closed
       to `unknown` rather than treating it as \"not defeq\" (which would
       risk a false `novel_in_imported_env` verdict). -/
    pure none

def compareTypes (targetType : Expr) (candidateType : Expr) (heartbeatBudget : Nat) :
    Lean.Elab.Term.TermElabM Bool := do
  match ← compareTypes? targetType candidateType heartbeatBudget with
  | some b => pure b
  | none => pure false

def eligibleByScope (env : Environment) (prefixes : Array String) (globalScope : Bool) (info : ConstantInfo) :
    Bool :=
  allowedKind info &&
  !Solve.Tools.AtomDump.shouldSkip info.name &&
  if globalScope then
    ownedByMathlib env info.name
  else
    Solve.Tools.AtomDump.matchesPrefix prefixes info.name

def readTargetsFile (path : String) : CommandElabM (Array Name) := do
  let contents ← IO.FS.readFile path
  let mut targets := #[]
  for rawLine in contents.splitOn "\n" do
    let line := rawLine.trimAscii.toString
    if !line.isEmpty then
      match Json.parse line with
      | .error err => throwError "could not parse targets JSONL line: {err}"
      | .ok json =>
          match json.getObjVal? "name" >>= Json.getStr? with
          | .error err => throwError "target record missing string name: {err}"
          | .ok nameRaw => targets := targets.push (parseName nameRaw)
  pure targets

def sortedConstants (env : Environment) : Array ConstantInfo :=
  env.constants.fold (fun acc _ info => acc.push info) #[]
    |>.qsort fun left right => left.name.cmp right.name == .lt

def findWitnessInCandidates
    (target : Name)
    (targetType : Expr)
    (candidateNames : Array Name)
    (env : Environment)
    (candidateCap : Nat)
    (heartbeatBudget : Nat) :
    Lean.Elab.Term.TermElabM (Option Name × Nat × Bool × Nat × Bool) := do
  /- Returns (witness, compared, capHit, bucketSize, uncertain).
     `uncertain = true` means at least one comparison was inconclusive
     (exception/timeout); the caller must emit `unknown` in that case. -/
  let bucketSize := candidateNames.size
  if bucketSize > candidateCap then
    pure (none, 0, true, bucketSize, false)
  else
    let mut compared := 0
    let mut witness : Option Name := none
    let mut uncertain := false
    for name in candidateNames do
      if witness.isNone && name != target then
        match env.find? name with
        | none => pure ()
        | some info =>
            compared := compared + 1
            match ← compareTypes? targetType info.type heartbeatBudget with
            | some true => witness := some info.name
            | some false => pure ()
            | none => uncertain := true
    pure (witness, compared, false, bucketSize, uncertain)

def emitTargetResult
    (target : Name)
    (targetInfo : ConstantInfo)
    (candidateNames : Array Name)
    (env : Environment)
    (candidateCap : Nat)
    (heartbeatBudget : Nat)
    (indexSize : Nat)
    (mode : String) : CommandElabM Unit := do
  try
    let targetType ← liftTermElabM <| instantiateMVars targetInfo.type
    let (witness, compared, capHit, bucketSize, uncertain) ←
      liftTermElabM <| findWitnessInCandidates target targetType candidateNames env candidateCap heartbeatBudget
    match witness with
    | some found =>
        emitNov (payload target "existing_defeq_duplicate" (some found) compared false
          "defeq match in imported environment" (some bucketSize) (some indexSize) (some mode))
    | none =>
      if uncertain then
        emitNov (payload target "unknown" none compared false "inconclusive comparison (exception or heartbeat timeout)"
          (some bucketSize) (some indexSize) (some mode))
      else if capHit then
          emitNov (payload target "unknown" none compared true "cap hit; not all candidates checked"
            (some bucketSize) (some indexSize) (some mode))
      else
          emitNov (payload target "novel_in_imported_env" none compared false "no imported defeq duplicate found"
            (some bucketSize) (some indexSize) (some mode))
  catch exc =>
    let message ← exc.toMessageData.toString
    emitNov (payload target "unknown" none 0 false ("probe_error: " ++ truncate message)
      none (some indexSize) (some mode))

def emitBruteTargetResult
    (target : Name)
    (targetInfo : ConstantInfo)
    (eligible : Array ConstantInfo)
    (candidateCap : Nat)
    (heartbeatBudget : Nat)
    (mode : String) : CommandElabM Unit := do
  try
    let limit := Nat.min candidateCap eligible.size
    let capped := eligible.extract 0 limit
    let mut compared := 0
    let mut witness : Option Name := none
    let mut uncertain := false
    let targetType ← liftTermElabM <| instantiateMVars targetInfo.type
    for info in capped do
      if witness.isNone && info.name != target then
        compared := compared + 1
        match ← liftTermElabM <| compareTypes? targetType info.type heartbeatBudget with
        | some true => witness := some info.name
        | some false => pure ()
        | none => uncertain := true
    match witness with
    | some found =>
        emitNov (payload target "existing_defeq_duplicate" (some found) compared false
          "defeq match in imported environment" (some eligible.size) (some eligible.size) (some mode))
    | none =>
        let capHit := eligible.size > candidateCap
        if uncertain then
          emitNov (payload target "unknown" none compared false "inconclusive comparison (exception or heartbeat timeout)"
            (some eligible.size) (some eligible.size) (some mode))
        else if capHit then
          emitNov (payload target "unknown" none compared true "cap hit; not all candidates checked"
            (some eligible.size) (some eligible.size) (some mode))
        else
          emitNov (payload target "novel_in_imported_env" none compared false "no imported defeq duplicate found"
            (some eligible.size) (some eligible.size) (some mode))
  catch exc =>
    let message ← exc.toMessageData.toString
    emitNov (payload target "unknown" none 0 false ("probe_error: " ++ truncate message)
      none (some eligible.size) (some mode))

def runBruteBatch
    (targets : Array Name)
    (eligible : Array ConstantInfo)
    (env : Environment)
    (candidateCap : Nat)
    (heartbeatBudget : Nat)
    (mode : String) : CommandElabM Unit := do
  for target in targets do
    match env.find? target with
    | none => emitNov (payload target "unknown" none 0 false "target not found" none (some eligible.size) (some mode))
    | some targetInfo =>
        emitBruteTargetResult target targetInfo eligible candidateCap heartbeatBudget mode

def runDiscrTreeBatch
    (targets : Array Name)
    (eligible : Array ConstantInfo)
    (env : Environment)
    (candidateCap : Nat)
    (heartbeatBudget : Nat)
    (mode : String) : CommandElabM Unit := do
  let mut tree : Lean.Meta.DiscrTree Name := {}
  for info in eligible do
    try
      tree ← liftTermElabM <| Lean.Meta.DiscrTree.insert tree info.type info.name
    catch _ =>
      pure ()
  for target in targets do
    match env.find? target with
    | none => emitNov (payload target "unknown" none 0 false "target not found" none (some eligible.size) (some mode))
    | some targetInfo =>
        try
          let targetType ← liftTermElabM <| instantiateMVars targetInfo.type
          let bucket ← liftTermElabM <| Lean.Meta.DiscrTree.getMatch tree targetType
          let bucket := bucket.qsort fun left right => left.cmp right == .lt
          emitTargetResult target targetInfo bucket env candidateCap heartbeatBudget eligible.size mode
        catch exc =>
          let message ← exc.toMessageData.toString
          emitNov (payload target "unknown" none 0 false ("probe_error: " ++ truncate message)
            none (some eligible.size) (some mode))

def emitIndex (mode : String) (globalScope : Bool) (indexSize : Nat) (targetCount : Nat) : CommandElabM Unit := do
  IO.println ("NOV_INDEX " ++ Json.compress (Json.mkObj [
    ("mode", toJson mode),
    ("global_scope", toJson globalScope),
    ("index_size", toJson indexSize),
    ("target_count", toJson targetCount)
  ]))

def runBatch : CommandElabM Unit := do
  let opts ← getOptions
  let targetsPath := solve.novelty.targetsFile.get opts
  let prefixRaw := solve.novelty.prefixes.get opts
  let prefixes := Solve.Tools.AtomDump.parsePrefixes prefixRaw
  let candidateCap := solve.novelty.candidateCap.get opts
  let heartbeatBudget := solve.novelty.heartbeatBudget.get opts
  let verifyMode := solve.novelty.verifyMode.get opts
  let globalScope := solve.novelty.globalScope.get opts
  let targets ← readTargetsFile targetsPath
  let env ← getEnv
  let constants := sortedConstants env
  let eligible := constants.filter (eligibleByScope env prefixes globalScope)
  if targets.isEmpty then
    emitIndex verifyMode globalScope eligible.size 0
    emitDone
    return
  if !globalScope && prefixes.isEmpty then
    for target in targets do
      emitNov (payload target "unknown" none 0 false "solve.novelty.prefixes is missing")
    emitIndex verifyMode globalScope eligible.size targets.size
    emitDone
    return
  if verifyMode == "brute" then
    runBruteBatch targets eligible env candidateCap heartbeatBudget "brute"
  else if verifyMode == "discrtree" then
    runDiscrTreeBatch targets eligible env candidateCap heartbeatBudget "discrtree"
  else
    for target in targets do
      emitNov (payload target "unknown" none 0 false ("unknown solve.novelty.verifyMode: " ++ verifyMode))
  emitIndex verifyMode globalScope eligible.size targets.size
  emitDone

def run : CommandElabM Unit := do
  try
    let opts ← getOptions
    let targetsPath := solve.novelty.targetsFile.get opts
    if !targetsPath.trimAscii.toString.isEmpty then
      runBatch
      return
    let targetRaw := solve.novelty.target.get opts
    let prefixRaw := solve.novelty.prefixes.get opts
    let prefixes := Solve.Tools.AtomDump.parsePrefixes prefixRaw
    let candidateCap := solve.novelty.candidateCap.get opts
    let heartbeatBudget := solve.novelty.heartbeatBudget.get opts
    if targetRaw.trimAscii.toString.isEmpty then
      emitNov (payload Name.anonymous "unknown" none 0 false "solve.novelty.target is missing")
      emitDone
      return
    if prefixes.isEmpty then
      emitNov (payload (parseName targetRaw) "unknown" none 0 false "solve.novelty.prefixes is missing")
      emitDone
      return
    let target := parseName targetRaw
    let env ← getEnv
    let some targetInfo := env.find? target
      | emitNov (payload target "unknown" none 0 false "target not found"); emitDone; return
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
    let mut uncertain := false
    let targetType ← liftTermElabM <| instantiateMVars targetInfo.type
    for info in capped do
      if witness.isNone then
        compared := compared + 1
        match ← liftTermElabM <| compareTypes? targetType info.type heartbeatBudget with
        | some true => witness := some info.name
        | some false => pure ()
        | none => uncertain := true
    match witness with
    | some found =>
        emitNov (payload target "existing_defeq_duplicate" (some found) compared false "defeq match in imported environment")
    | none =>
        let capHit := eligible.size > candidateCap
        /- Fail-closed: if the cap was hit we did not check all candidates, so
           we cannot confirm novelty. Report \"unknown\" instead of \"novel\". -/
        if uncertain then
          emitNov (payload target "unknown" none compared false "inconclusive comparison (exception or heartbeat timeout)")
        else if capHit then
          emitNov (payload target "unknown" none compared true "cap hit; not all candidates checked")
        else
          emitNov (payload target "novel_in_imported_env" none compared false "no imported defeq duplicate found")
    emitDone
  catch exc =>
    let opts ← getOptions
    let targetRaw := solve.novelty.target.get opts
    let target := if targetRaw.trimAscii.toString.isEmpty then Name.anonymous else parseName targetRaw
    let message ← exc.toMessageData.toString
    emitNov (payload target "unknown" none 0 false ("probe_error: " ++ truncate message))
    emitDone

elab "#solve_novelty_probe" : command => run

end Solve.Tools.NoveltyProbe
