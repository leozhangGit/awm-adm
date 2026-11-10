import Init

/- ADM's invariant proof pattern. The transition relation includes legal actions
   only. Reach includes the initial state, so a zero-step goal is not excluded.
   Concrete tables and premises are appended by the local certificate checker. -/
namespace ADM

inductive Reach (edge : Nat → Nat → Prop) (initial : Nat) : Nat → Prop where
  | start : Reach edge initial initial
  | step {s t : Nat} : Reach edge initial s → edge s t → Reach edge initial t

theorem invariant {edge : Nat → Nat → Prop} {initial : Nat} {I : Nat → Prop}
    (starts : I initial) (preserves : ∀ s t, I s → edge s t → I t)
    {s : Nat} (reached : Reach edge initial s) : I s := by
  induction reached with
  | start => exact starts
  | step prior action ih => exact preserves _ _ ih action

theorem excludes_goal {edge : Nat → Nat → Prop} {initial : Nat}
    {I G : Nat → Prop} (starts : I initial)
    (preserves : ∀ s t, I s → edge s t → I t)
    (excludes : ∀ s, I s → ¬ G s)
    {s : Nat} (reached : Reach edge initial s) : ¬ G s :=
  excludes s (invariant starts preserves reached)

end ADM
