# Agent Smith — Model Benchmark Report

> Comparison of **5 models** across **≥ 2 providers** on the **same 3 SWE-bench tasks**, using the Agent Smith SWE-bench agent loop.
> Raw solve rate is only part of the story: this report also measures exploration efficiency, token cost, provider reliability and submission discipline.
>
> Every number in this report comes from the `solution.json` files stored in [`benchmark/`](benchmark/) (see [Appendix A](#appendix-a--backing-files)).

---

## Table of contents

1. [Setup](#1-setup)
2. [Results](#2-results)
3. [Provider reliability](#3-provider-reliability)
4. [Intermediary metrics](#4-intermediary-metrics)
5. [Ablation study](#5-ablation-study)
6. [Conclusions](#6-conclusions)
- [Appendix A — Backing files](#appendix-a--backing-files)
- [Appendix B — How to reproduce](#appendix-b--how-to-reproduce)

---

## 1. Setup

### 1.1 Models and providers

| # | Model | Provider | Base URL | Why it was included |
|---|-------|----------|----------|----------------|------------------------------------|---------------------|
| 1 | `gemini-flash-lite-latest` | google ai studio | `https://generativelanguage.googleapis.com/v1beta/openai/` | fast responses and good thinking |
| 2 | `nvidia-nemotron-3-ultra` | openrouter | `https://openrouter.ai/api/v1` | good scores during test phase |
| 3 | `nvidia-nemotron-3.5-super-vl` | openrouter | `https://openrouter.ai/api/v1` | The best balance between speed and thinking |
| 4 | `qwen-qwen3.8-27b` | groq | `https://api.groq.com/openai/v1` | Was very good during test, iterations didn't pass over 7 iterations |
| 5 | `recursive-flint-v1.0` | openrouter | `https://openrouter.ai/api/v1` | Giving a chance to a newbie I guess |


### 1.2 Tasks

| # | Instance ID | Repository | Type of bug / change |
|---|-------------|------------|----------------------|
| T1 | `scikit-learn__scikit-learn-13439` | scikit-learn/scikit-learn | Implement a __len__ funtion |
| T2 | `pytest-dev__pytest-7432` | pytest-dev/pytest | Fix the bug in pytest_runtest_makereport |
| T3 | `django__django-11099` | django/django | Change a regex so usernames ending with trailing newlines are rejected |

**Why these tasks were selected:**

- **T1 — TBD:** Implement a function iside a file. See if the model edit files correctly.
- **T2 — TBD:** Requires searching the codebase to locate the bug: tests exploration.
- **T3 — TBD:** Answer is given in the problem statement, to see if the model actually read it and pay attention to it.

---

## 2. Results


### 2.1 Model 1 — `gemini-flash-lite-latest` (provider: googleapis)

| Task | Pass/Fail | Iterations used | Total input tokens | Total output tokens | Wall-clock time | Stop reason | solution.json |
|------|-----------|-----------------|--------------------|---------------------|-----------------|-------------|---------------|
| T1 `scikit-learn__scikit-learn-13439` | ✅ Pass | 11 | 84,866 | 719 | 00:27 | final_answer | [link](benchmark/gemini-flash-lite-latest/before/solution_1.json) |
| T2 `pytest-dev__pytest-7432` | ✅ Pass | 13 | 102,574 | 493 | 00:39 | final_answer | [link](benchmark/gemini-flash-lite-latest/before/solution_2.json) |
| T3 `django__django-11099` | ❌ Fail | 18 | 53,370 | 102 | 00:21 | provider_error | [link](benchmark/gemini-flash-lite-latest/before/solution_3.json) |
| **Total / Avg** | **2 / 3** | **avg 14.0** | **240,810** | **1,314** | **01:27** | — | — |


### 2.2 Model 2 — `nvidia/nemotron-3-ultra-550b-a55b:free` (provider: openrouter)

| Task | Pass/Fail | Iterations used | Total input tokens | Total output tokens | Wall-clock time | Stop reason | solution.json |
|------|-----------|-----------------|--------------------|---------------------|-----------------|-------------|---------------|
| T1 `scikit-learn__scikit-learn-13439` | ✅ Pass | 10 | 91,552 | 1,572 | 01:01 | final_answer | [link](benchmark/nvidia-nemotron-3-ultra/before/solution_1.json) |
| T2 `pytest-dev__pytest-7432` | ❌ Fail | 30 | 499,317 | 3,529 | 02:15 | max_iterations | [link](benchmark/nvidia-nemotron-3-ultra/before/solution_2.json) |
| T3 `django__django-11099` | ❌ Fail | 30 | 758,328 | 7,331 | 03:37 | max_iterations | [link](benchmark/nvidia-nemotron-3-ultra/before/solution_3.json) |
| **Total / Avg** | **1 / 3** | **avg 23.3** | **1,349,197** | **12,432** | **06:53** | — | — |


### 2.3 Model 3 — `nvidia/nemotron-3.5-super-vl:free` (provider: openrouter)

| Task | Pass/Fail | Iterations used | Total input tokens | Total output tokens | Wall-clock time | Stop reason | solution.json |
|------|-----------|-----------------|--------------------|---------------------|-----------------|-------------|---------------|
| T1 `scikit-learn__scikit-learn-13439` | ✅ Pass | 12 | 102,173 | 1,583 | 00:41 | final_answer | [link](benchmark/nvidia-nemotron-3.5-super-vl/before/solution_1.json) |
| T2 `pytest-dev__pytest-7432` | ✅ Pass | 12 | 126,027 | 8,204 | 02:11 | final_answer | [link](benchmark/nvidia-nemotron-3.5-super-vl/before/solution_2.json) |
| T3 `django__django-11099` | ❌ Fail | 7 | 69,072 | 10,000 | 02:07 | max_tokens | [link](benchmark/nvidia-nemotron-3.5-super-vl/before/solution_3.json) |
| **Total / Avg** | **2 / 3** | **avg 10.3** | **297,272** | **19,787** | **04:59** | — | — |

**Notes:** TBD

### 2.4 Model 4 — `qwen/qwen3.8-27b` (provider: groq)

| Task | Pass/Fail | Iterations used | Total input tokens | Total output tokens | Wall-clock time | Stop reason | solution.json |
|------|-----------|-----------------|--------------------|---------------------|-----------------|-------------|---------------|
| T1 `scikit-learn__scikit-learn-13439` | ❌ Fail | 3 | 16,098 | 229 | 01:21 | provider_error | [link](benchmark/qwen-qwen3.8-27b/before/solution_1.json) |
| T2 `pytest-dev__pytest-7432` | ❌ Fail | 4 | 20,742 | 2,007 | 02:04 | provider_error | [link](benchmark/qwen-qwen3.8-27b/before/solution_2.json) |
| T3 `django__django-11099` | ❌ Fail | 2 | 8,467 | 78 | 00:15 | final_answer | [link](benchmark/qwen-qwen3.8-27b/before/solution_3.json) |
| **Total / Avg** | **0 / 3** | **avg 3.0** | **45,307** | **2,314** | **03:40** | — | — |

**Notes:** TBD

### 2.5 Model 5 — `recursive/flint-v1.0:free` (provider: openrouter)

| Task | Pass/Fail | Iterations used | Total input tokens | Total output tokens | Wall-clock time | Stop reason | solution.json |
|------|-----------|-----------------|--------------------|---------------------|-----------------|-------------|---------------|
| T1 `scikit-learn__scikit-learn-13439` | ✅ Pass | 10 | 90,257 | 4,706 | 00:51 | final_answer | [link](benchmark/recursive-flint-v1.0/before/solution_1.json) |
| T2 `pytest-dev__pytest-7432` | ❌ Fail | 1 | 2,770 | 10,000 | 01:16 | max_tokens | [link](benchmark/recursive-flint-v1.0/before/solution_2.json) |
| T3 `django__django-11099` | ❌ Fail | 0 | 0 | 0 | 00:04 | provider_error | [link](benchmark/recursive-flint-v1.0/before/solution_3.json) |
| **Total / Avg** | **1 / 3** | **avg 3.7** | **93,027** | **14,706** | **02:11** | — | — |

**Notes:** TBD

### 2.6 Summary across models

| Model | Provider | Solved | Avg iterations | Avg input tokens | Avg output tokens | Avg wall-clock | Tokens per solved task |
|-------|----------|--------|----------------|------------------|-------------------|----------------|------------------------|
| `gemini-flash-lite-latest` | googleapis | 2 / 3 | 14.0 | 80,270 | 438 | 00:29 | 121,062 |
| `nvidia/nemotron-3-ultra-550b-a55b:free` | openrouter | 1 / 3 | 23.3 | 449,732 | 4,144 | 02:18 | 1,361,629 |
| `nvidia/nemotron-3.5-super-vl:free` | openrouter | 2 / 3 | 10.3 | 99,091 | 6,596 | 01:40 | 158,529 |
| `qwen/qwen3.8-27b` | groq | 0 / 3 | 3.0 | 15,102 | 771 | 01:13 | ∞ |
| `recursive/flint-v1.0:free` | openrouter | 1 / 3 | 3.7 | 31,009 | 4,902 | 00:44 | 107,733 |

---

## 3. Provider reliability

**How it is measured (from `StepMetrics` in each solution.json):**

- **Average response time per request** = mean of `request_time_ms` over every LLM request of the model (all 3 tasks).
- **Retries** = sum of the `retries` field, split by cause (HTTP 429 rate limit, timeout, 5xx / other error).
- **Availability** = successful requests / total request attempts (successful + failed attempts), in %.

## 3. Provider reliability

| Model | Provider | Total requests | Avg response time (ms) | Min / Max (ms) | Retries — 429 | Retries — timeout | Retries — 5xx / other | Total retries | Key rotations | Availability |
|-------|----------|----------------|------------------------|----------------|---------------|-------------------|-----------------------|---------------|---------------|--------------|
| `gemini-flash-lite-latest` | googleapis | 42 | 1,200 | 570 / 7,102 | N/A | N/A | N/A | 0 | N/A | 97.7 % |
| `nvidia/nemotron-3-ultra-550b-a55b:free` | openrouter | 70 | 4,807 | 1,061 / 32,837 | N/A | N/A | N/A | 2 | N/A | 97.2 % |
| `nvidia/nemotron-3.5-super-vl:free` | openrouter | 31 | 7,673 | 884 / 52,842 | N/A | N/A | N/A | 4 | N/A | 88.6 % |
| `qwen/qwen3.8-27b` | groq | 9 | 21,587 | 507 / 60,265 | N/A | N/A | N/A | 0 | N/A | 81.8 % |
| `recursive/flint-v1.0:free` | openrouter | 11 | 10,062 | 1,846 / 72,597 | N/A | N/A | N/A | 2 | N/A | 78.6 % |

**Observations:** TBD (e.g. which provider hit its daily quota, at what time of day, whether key rotation was enough, whether a run had to be restarted).

---

## 4. Intermediary metrics

**Definitions (measured manually from the steps in each solution.json):**

- **M1 — Exploration efficiency:** first step at which the agent reads (`read_file`) or edits (`edit_file`) a file that appears in the final patch (`diff --git` headers of `get_patch()`). Lower is better.
- **M2 — Partial progress:** first step at which the number of failing tests is lower than the baseline (failures of the first `run_tests` call, before any edit). Lower is better. N/A if tests were never run.
- **M3 — Submission discipline:** number of iterations between the first step where all target tests pass and the `final_answer` step. **0 is ideal.** N/A if tests never fully passed.

### 4.1 Model 1 — `gemini-flash-lite-latest`

| Task | Total steps | M1 — First relevant file touched (step) | M2 — First decrease in failures (step) | M3 — Iterations between tests pass and final_answer |
|------|-------------|-----------------------------------------|----------------------------------------|-----------------------------------------------------|
| T1 | 11 | 4 | 10 | 0 |
| T2 | 13 | 6 | 11 | 1 |
| T3 | 18 | N/A (no patch) | N/A | N/A |

### 4.2 Model 2 — `nvidia/nemotron-3-ultra-550b-a55b:free`

| Task | Total steps | M1 — First relevant file touched (step) | M2 — First decrease in failures (step) | M3 — Iterations between tests pass and final_answer |
|------|-------------|-----------------------------------------|----------------------------------------|-----------------------------------------------------|
| T1 | 10 | 3 | 8 | 1 |
| T2 | 30 | N/A (no patch) | never | N/A |
| T3 | 30 | N/A (no patch) | N/A | N/A |

### 4.3 Model 3 — `nvidia/nemotron-3.5-super-vl:free`

| Task | Total steps | M1 — First relevant file touched (step) | M2 — First decrease in failures (step) | M3 — Iterations between tests pass and final_answer |
|------|-------------|-----------------------------------------|----------------------------------------|-----------------------------------------------------|
| T1 | 12 | 3 | 11 | 0 |
| T2 | 12 | 3 | 11 | 0 |
| T3 | 7 | N/A (no patch) | N/A | N/A |

### 4.4 Model 4 — `qwen/qwen3.8-27b`

| Task | Total steps | M1 — First relevant file touched (step) | M2 — First decrease in failures (step) | M3 — Iterations between tests pass and final_answer |
|------|-------------|-----------------------------------------|----------------------------------------|-----------------------------------------------------|
| T1 | 3 | N/A (no patch) | never | N/A |
| T2 | 4 | N/A (no patch) | never | N/A |
| T3 | 2 | N/A (no patch) | N/A | N/A |

### 4.5 Model 5 — `recursive/flint-v1.0:free`

| Task | Total steps | M1 — First relevant file touched (step) | M2 — First decrease in failures (step) | M3 — Iterations between tests pass and final_answer |
|------|-------------|-----------------------------------------|----------------------------------------|-----------------------------------------------------|
| T1 | 10 | 3 | 9 | 0 |
| T2 | 1 | N/A (no patch) | N/A | N/A |
| T3 | 0 | N/A (no patch) | N/A | N/A |

### 4.6 Analysis

- `nvidia/nemotron-3.5-super-vl:free` find the right file fastest, and have the best M3 score.

---

## 5. Ablation study

### 5.1 Change tested

**Component changed**
- Prompt:
    1. Told the model to not use python block \
    for example code.
    2. If the issue give a file or regex pattern, go \
    straight to it.
    3. Read the problem statement more carefully to \
    clearly understand what is expected.
- Tools:
    1. modified the run_test() tool to make sure that \
    the output of the setup and teardown are not printed to the output.
    2. Corrected the search code tool to use \
    pattern correctly.
- Parameter:
    1. Limited the max_token_output to a maximum \
    value of 2045 tokens.
    2. If no content is found in the answer, retry \
    until max_retries then return error.

**Before**
- Models did not fully understand what was expected from \
them because of the bad truncation of run_tests() and \
unprecise message that were given.

**Hypothesis**
- After the changes cited upward, I hope that the model \
will now have a better idea of what to fix and where to fix it. \
Which will make it more decided during changes.

**Model used**
- `gemini-flash-lite-latest`
- `nvidia-nemotron-3-ultra`
- `nvidia-nemotron-3.5-super-vl`
- `qwen-qwen3.8-27b`
Did not use `recursive-flint` because it keep changing it's tool format \
output, and use python on top of it.

**Tasks**
- same tasks for both runs


### 5.2 Before / after results

Totals over the 3 tasks, per model:

| Model | Solved (before → after) | Iterations (before → after) | Input tokens (before → after) | Output tokens (before → after) | Wall-clock (before → after) |
|-------|-------------------------|-----------------------------|-------------------------------|--------------------------------|-----------------------------|
| `gemini-flash-lite-latest` | 2 / 3 → 0 / 3 | 42 → 0 | 240,810 → 0 | 1,314 → 0 | 01:27 → 00:34 |
| `nvidia/nemotron-3-ultra-550b-a55b:free` | 1 / 3 → 3 / 3 | 70 → 40 | 1,349,197 → 347,189 | 12,432 → 7,954 | 06:53 → 06:02 |
| `nvidia/nemotron-3.5-super-vl:free` | 2 / 3 → 3 / 3 | 31 → 26 | 297,272 → 173,464 | 19,787 → 11,206 | 04:59 → 02:38 |
| `qwen/qwen3.8-27b` | 0 / 3 → 0 / 3 | 9 → 17 | 45,307 → 80,686 | 2,314 → 4,735 | 03:40 → 09:07 |
| **All models** | 5 / 12 → 6 / 12 | 152 → 83 | 1,932,586 → 601,339 | 35,847 → 23,895 | 16:59 → 18:21 |

#### 5.2.1 `gemini-flash-lite-latest`

| Task | Version | Pass/Fail | Iterations | Input tokens | Output tokens | Wall-clock | Stop reason | M1 | M2 | M3 |
|------|---------|-----------|------------|--------------|---------------|------------|-------------|----|----|----|
| T1 | [Before](benchmark/gemini-flash-lite-latest/before/solution_1.json) | ✅ Pass | 11 | 84,866 | 719 | 00:27 | final_answer | 4 | 10 | 0 |
| T1 | [After](benchmark/gemini-flash-lite-latest/after/solution_1.json) | ❌ Fail | 0 | 0 | 0 | 00:08 | provider_error | N/A (no patch) | N/A | N/A |
| T2 | [Before](benchmark/gemini-flash-lite-latest/before/solution_2.json) | ✅ Pass | 13 | 102,574 | 493 | 00:39 | final_answer | 6 | 11 | 1 |
| T2 | [After](benchmark/gemini-flash-lite-latest/after/solution_2.json) | ❌ Fail | 0 | 0 | 0 | 00:19 | provider_error | N/A (no patch) | N/A | N/A |
| T3 | [Before](benchmark/gemini-flash-lite-latest/before/solution_3.json) | ❌ Fail | 18 | 53,370 | 102 | 00:21 | provider_error | N/A (no patch) | N/A | N/A |
| T3 | [After](benchmark/gemini-flash-lite-latest/after/solution_3.json) | ❌ Fail | 0 | 0 | 0 | 00:07 | provider_error | N/A (no patch) | N/A | N/A |
| **Δ (After − Before)** | — | **-2 solved** | **-42** | **-240,810** | **-1,314** | **-00:53** | — | N/A | N/A | N/A |

#### 5.2.2 `nvidia/nemotron-3-ultra-550b-a55b:free`

| Task | Version | Pass/Fail | Iterations | Input tokens | Output tokens | Wall-clock | Stop reason | M1 | M2 | M3 |
|------|---------|-----------|------------|--------------|---------------|------------|-------------|----|----|----|
| T1 | [Before](benchmark/nvidia-nemotron-3-ultra/before/solution_1.json) | ✅ Pass | 10 | 91,552 | 1,572 | 01:01 | final_answer | 3 | 8 | 1 |
| T1 | [After](benchmark/nvidia-nemotron-3-ultra/after/solution_1.json) | ✅ Pass | 14 | 108,414 | 2,056 | 01:31 | final_answer | 2 | 12 | 1 |
| T2 | [Before](benchmark/nvidia-nemotron-3-ultra/before/solution_2.json) | ❌ Fail | 30 | 499,317 | 3,529 | 02:15 | max_iterations | N/A (no patch) | never | N/A |
| T2 | [After](benchmark/nvidia-nemotron-3-ultra/after/solution_2.json) | ✅ Pass | 10 | 121,226 | 3,647 | 02:13 | final_answer | 2 | 7 | 2 |
| T3 | [Before](benchmark/nvidia-nemotron-3-ultra/before/solution_3.json) | ❌ Fail | 30 | 758,328 | 7,331 | 03:37 | max_iterations | N/A (no patch) | N/A | N/A |
| T3 | [After](benchmark/nvidia-nemotron-3-ultra/after/solution_3.json) | ✅ Pass | 16 | 117,549 | 2,251 | 02:18 | final_answer | 7 | 14 | 1 |
| **Δ (After − Before)** | — | **+2 solved** | **-30** | **-1,002,008** | **-4,478** | **-00:51** | — | -1.0 (n=1) | +4.0 (n=1) | +0.0 (n=1) |

#### 5.2.3 `nvidia/nemotron-3.5-super-vl:free`

| Task | Version | Pass/Fail | Iterations | Input tokens | Output tokens | Wall-clock | Stop reason | M1 | M2 | M3 |
|------|---------|-----------|------------|--------------|---------------|------------|-------------|----|----|----|
| T1 | [Before](benchmark/nvidia-nemotron-3.5-super-vl/before/solution_1.json) | ✅ Pass | 12 | 102,173 | 1,583 | 00:41 | final_answer | 3 | 11 | 0 |
| T1 | [After](benchmark/nvidia-nemotron-3.5-super-vl/after/solution_1.json) | ✅ Pass | 8 | 43,492 | 1,386 | 00:32 | final_answer | 2 | N/A (baseline 0) | 0 |
| T2 | [Before](benchmark/nvidia-nemotron-3.5-super-vl/before/solution_2.json) | ✅ Pass | 12 | 126,027 | 8,204 | 02:11 | final_answer | 3 | 11 | 0 |
| T2 | [After](benchmark/nvidia-nemotron-3.5-super-vl/after/solution_2.json) | ✅ Pass | 6 | 31,024 | 4,862 | 00:54 | final_answer | 1 | N/A (baseline 0) | 0 |
| T3 | [Before](benchmark/nvidia-nemotron-3.5-super-vl/before/solution_3.json) | ❌ Fail | 7 | 69,072 | 10,000 | 02:07 | max_tokens | N/A (no patch) | N/A | N/A |
| T3 | [After](benchmark/nvidia-nemotron-3.5-super-vl/after/solution_3.json) | ✅ Pass | 12 | 98,948 | 4,958 | 01:12 | final_answer | 7 | 10 | 1 |
| **Δ (After − Before)** | — | **+1 solved** | **-5** | **-123,808** | **-8,581** | **-02:21** | — | -1.5 (n=2) | N/A | +0.0 (n=2) |

#### 5.2.4 `qwen/qwen3.8-27b`

| Task | Version | Pass/Fail | Iterations | Input tokens | Output tokens | Wall-clock | Stop reason | M1 | M2 | M3 |
|------|---------|-----------|------------|--------------|---------------|------------|-------------|----|----|----|
| T1 | [Before](benchmark/qwen-qwen3.8-27b/before/solution_1.json) | ❌ Fail | 3 | 16,098 | 229 | 01:21 | provider_error | N/A (no patch) | never | N/A |
| T1 | [After](benchmark/qwen-qwen3.8-27b/after/solution_1.json) | ❌ Fail | 6 | 30,260 | 646 | 03:28 | provider_error | N/A (no patch) | 6 | never submitted |
| T2 | [Before](benchmark/qwen-qwen3.8-27b/before/solution_2.json) | ❌ Fail | 4 | 20,742 | 2,007 | 02:04 | provider_error | N/A (no patch) | never | N/A |
| T2 | [After](benchmark/qwen-qwen3.8-27b/after/solution_2.json) | ❌ Fail | 3 | 11,329 | 2,225 | 01:45 | provider_error | N/A (no patch) | N/A | N/A |
| T3 | [Before](benchmark/qwen-qwen3.8-27b/before/solution_3.json) | ❌ Fail | 2 | 8,467 | 78 | 00:15 | final_answer | N/A (no patch) | N/A | N/A |
| T3 | [After](benchmark/qwen-qwen3.8-27b/after/solution_3.json) | ❌ Fail | 8 | 39,097 | 1,864 | 03:54 | provider_error | N/A (no patch) | 8 | never submitted |
| **Δ (After − Before)** | — | **+0 solved** | **+8** | **+35,379** | **+2,421** | **+05:27** | — | N/A | N/A | N/A |

**Remarque**
- `gemini-flash-lite-latest` did not even answer for the 3 tasks, \
which prove that the provider availability is weak.
- `qwen/qwen3.8-27b` could have been the best model for all runs, \
but it was nerfed because of it's internal max input token that was 7000. \
2/3 runs were just missing one step, the final_answer() and one was missing \
the run_tests() and final_answer() which is a very good score overall, and \
will be tested with openrouter provider later on to see it's performance without \
groq's limitation.
---

## 6. Conclusions

### 6.1 Selected model(s) for the final pipeline

| Role | Model | Provider | Reason (based on the data above) |
|------|-------|----------|----------------------------------|
| Primary | `qwen/qwen3.8-27b` | groq | The shortest and most intelligent model. |
| Fallback | `nvidia/nemotron-3.5-super-vl:free` | openrouter | Used to finish the task when qwen is out of token |

### 6.2 Models that can be disregarded

| Model | Provider | Reason (based on the data above) |
|-------|----------|----------------------------------|
| `gemini-flash-lite-latest` | google-ai-studio | Provider availability is extremly weak |
| `recursive-flint-v1.0` | openrouter | Strange tool calls and mix it with python code |


### 6.3 Limitations

- Only 3 tasks and one run per model × task: results have high variance and are not statistically significant.
- Free-tier quotas and provider load change during the day, which affects response times and retries.

---

## Appendix A — Backing files

All runs are stored in the repository:

```
benchmark/
├── model_1/
│   ├── before/solution1.json
│   └── after/solution1.json
├── model_2/ ...
├── model_3/ ...
├── model_4/ ...
├── model_5/ ...
└── tasks/
    ├── task-1.json
    └── task-2.json
```

## Appendix B — How to reproduce

```bash
uv run agent_swebench --provider-url <PROVIDER_URL> --model <MODEL_NAME> --task <TASK_FILE> --output benchmark/<model>/<task>/solution.json
```