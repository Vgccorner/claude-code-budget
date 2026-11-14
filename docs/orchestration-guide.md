# Orchestration guide

One aim: finish the work in the fewest tokens that still pass the checks. On a subscription the usage cap is the budget, so tokens are the money.

Roles map to models in the `agents/` files (defaults: Orchestrator = Opus, Worker = Sonnet, Bulk = Haiku). Change the `model:` line to change the mapping; nothing else hard-codes it.

## The lead

The thread you start is the **lead**. It does the rest without being asked:

1. **Size the job.** A few tool calls: just do it, stop here.
2. **Split it into pieces** and give each a role and effort (section 3).
3. **Find your own role.** A model that is not in your role table, or costs more than the Orchestrator's, counts as above Orchestrator.
4. **Route each piece.**
   - Role below yours: hand it to an agent of that role. The costlier the lead, the less it does by hand: a lead above Orchestrator plans, briefs, checks and decides; it builds nothing.
   - Role is yours: do it yourself. Never spawn your own role just to hand a job across.
   - Role above yours: do what you can, then hand only the hard part (the design, the review) up, and log it as an escalation.
5. **Check** each result (section 5), then report.

Subagents do not spawn subagents. The lead holds the plan; an agent does its brief and reports back.

## 1. What things cost

These figures come from measuring 400 subagent logs of one multi-agent pipeline (see the README). Measure your own with `session_cost.py`; the shape holds in general.

- **Every turn re-reads the whole context.** Cost of a thread = context size x number of turns. A long lead thread is the biggest cost there is: on early runs, 36-72% of the cost was the lead re-reading 470-585k tokens per turn.
- **Every agent starts at about 59k tokens** before it reads its brief (system prompt, tools, project files). A two-turn reader costs about 120k. A typical builder runs about 7 turns, ends near 90k of context and costs about 0.5M.
- **A resumed agent only grows.** Builders resumed for fix rounds reached 700-970k of context.
- **What an agent returns lands in the caller's context for good** and is re-read on every later turn.

So an agent is not free parallelism. It is a 59k entry fee that pays off only when it keeps more than that out of a costlier thread, or does the work on a cheaper role.

## 2. When to orchestrate

Take the first line that fits.

| The work | Do this |
|---|---|
| A handful of tool calls, a lookup with a known target, one edit, a one-command step | Do it in the current thread. No agent. |
| Reading or searching more than about 30k tokens when only the conclusion is needed | One agent on the cheapest role that can do it. It returns the conclusion, not the files. |
| One build item with a runnable check (tests, lint) | One Worker, the check as its done-when. |
| Two or more pieces that share no files and don't need each other's results | One agent each, launched in one message. |
| A judgment that must not be anchored on the author's view (critic, blind reader, review) | A fresh agent given the work, not the author's opinion of it. |
| The same step over many items (tagging, readers, critics) | A scripted fan-out, with its estimate written down first (section 7). |
| A whole production step, or the lead is past about 200k tokens | Save a hand-over note and continue in a fresh session. |

Don't orchestrate when:
- the brief would be longer than the work;
- the caller must read the full result anyway (read the source directly);
- the pieces touch the same files or must land as one change;
- it is a check you could run inline;
- you already delegated it. Wait for the result; never also run it yourself.

## 3. Role and effort

Every spawn names a role, and the role sets the model and the default effort. Never inherit: the lead often runs at a high effort on the costliest model in use. The hook in `hooks/require_model.py` enforces this.

| Task | Role | Effort |
|---|---|---|
| File prep, copying, tagging, dedupe, format checks, simple yes/no readers | Bulk | low |
| Search and read-to-conclusion across many files | Bulk; Worker if it must weigh evidence | low |
| Build, write, research synthesis, blind testers, critics | Worker | medium |
| A build that failed once on a hard point, or a tricky single item where a miss means a new builder | Worker | high |
| Scope card, plan, review against the bar, a rule or design many pieces will follow | Orchestrator | medium |
| A build that spans systems, or one a Worker failed its checks on | Orchestrator | medium |
| A design that sets the shape of the whole system | Orchestrator | high |

- **Right-size the first time.** Pick the role and effort most likely to pass in one pass. One Worker at high costs less than a Worker at medium plus a second builder.
- **Escalate one step at a time**, and only after a failed check: effort first, then role. Log each escalation.
- The lead plans and checks. It does not build, and it does not read what an agent could read for it.

## 4. The brief

The agent knows only the brief. A bad brief is paid for twice: once for the wrong work, once for the redo. Every brief has these seven parts, in this order:

1. **Goal** in one sentence, and what it is for.
2. **Read these**: exact paths, and line ranges for big files. Name what not to read.
3. **Already settled or ruled out**, so it is not re-decided.
4. **Scope**: the files it may change. Everything else is off limits. It deletes nothing.
5. **Done when**: the command that must pass, or the bar to meet.
6. **Return**: the format and a size cap.
7. **Stop rule**: stop and report at the first real blocker, or at about 200k of context.

Rules for briefs:
- Low-effort Bulk agents get the brief and the material pasted inline, with "do the task now, reply only with your answers". Given only file paths, they tend to summarise the brief. Workers handle paths fine.
- Point Workers and up at files instead of pasting them. Paste only what is short and essential.
- Tell every agent to batch independent tool calls in one turn. Fewer turns is the saving.
- Don't hand a reviewer your conclusion. It will come back confirmed.

## 5. Results, checks and fix rounds

- **Return little.** Default cap: 300 words. Shape: verdict, what changed (paths), what was not verified. Long output goes to a file; the agent returns the path and a one-line verdict.
- **Give structured jobs a fixed answer shape** (scores, pass/fail, a list), so no one reads prose to use it.
- **A report is not proof.** Run the check or read the diff before calling it done.
- **Fix rounds: never resume a builder.** A new builder gets a short brief: what failed, the failing output, the files. At most one fix round per item; after that, escalate one step or take it to a human.
- **Small fixes** (a few lines, a known spot) are done by the caller. A new agent's entry fee is more than the fix.
- **Caps.** One fix round, a fixed number of render or retry loops, a fixed number of parallel builds, and one heavy local job at a time. Log whatever a cap drops.
- **Score noise.** Critic totals move 2-3 points between fresh panels of the same piece. Don't spend a round to win one point.

## 6. Fan-outs and side sessions

- Scripted fan-outs (many agents from one script): fewer than about 10 agents unless you set another size; role and effort set on every call; a fixed answer shape on every agent; verify each piece as it finishes, not in a batch at the end.
- Probe 2-3 options with a quick test. Don't build all the options in full.
- A **side session** is for a task that stands alone and ends in its own result (a branch, a published piece). A piece of the task at hand goes to an agent instead.
- A **fork** carries the caller's whole context and model on every turn. Use one only while the thread is short (under about 100k) and the task leans on most of it.

## 7. Budget

- **Estimate before any fan-out:** agents x about 60k x expected turns, per role. Put the number in the plan. If it is more than about 5M, say so before launching.
- **Write the prediction down.** Agents, renders or retries, tokens. Then compare it with the measured run; the gap is what the next change to this guide should come from.
- **Pace** against your plan's cap: check usage before each big step. Ahead of pace: run only cheap pending work, or wait.
- **After a run,** run `python3 session_cost.py latest`. Note agents, roles, tokens and the lead's share next to the prediction. A thread over the 200k limit is a miss.

## 8. Before you spawn

1. Could the current thread do this in a few calls? Then do it.
2. Role and effort chosen from section 3 and set on the call?
3. Brief has all seven parts and a return cap?
4. Is there a check that decides done?
5. No two writers on the same files?
6. For more than 3 agents: estimate written down, pace checked?
