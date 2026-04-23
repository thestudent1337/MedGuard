# MedGuard

<img width="2565" height="1880" alt="image" src="https://github.com/user-attachments/assets/300d848a-a869-489a-9863-44df305e697c" />


MedGuard is a mock healthcare assistant built for a high-risk AI-in-healthcare course project. It compares three prompt-monitoring strategies in front of a tool-using chatbot:

- `heuristic` detection
- `llm` detection
- `hybrid` detection

The system uses **synthetic patient data only** and is designed to study whether a healthcare chatbot can detect malicious or policy-violating prompts before accessing or modifying protected medical data.

## Project Goal

The project asks a simple systems question:

**What kind of monitoring layer works best for a healthcare chatbot connected to healthcare tools and records?**

To answer that, MedGuard:

- simulates a healthcare assistant over a fake EHR
- plans tool calls from natural-language prompts
- applies a monitoring layer before execution
- enforces policy decisions such as `allow`, `allow_with_logging`, `require_reauthentication`, `block_and_log`, and `block_and_alert`
- evaluates detector quality on both **security correctness** and **write integrity**

## What the System Includes

- Browser-based frontend for interactive prompt testing
- Evaluation page for running benchmark cases
- SQLite-backed mock EHR with synthetic patient data
- Planner that maps user prompts to structured actions
- Three detector modes: heuristic, LLM-only, and hybrid
- Policy engine for request gating
- Incident logging for suspicious or blocked activity
- Benchmark dataset with benign and adversarial prompt categories
- Unit tests for core functionality

## Research Focus

The benchmark compares detectors across categories such as:

- benign single-record access
- benign self-service updates
- benign cohort queries
- unauthorized access
- unauthorized modification
- prompt injection
- system prompt extraction
- bulk PHI exfiltration
- sensitive inference
- role impersonation
- multilingual prompts

The project also includes a **semantic-challenge** slice: prompts designed to avoid obvious trigger phrases so the system can test whether detectors understand malicious intent semantically rather than only through keyword patterns.

## Repo Structure

```text
high-risk-project/
├── src/medguard/
│   ├── app.py
│   ├── chatbot.py
│   ├── evaluator.py
│   ├── eval_cases.py
│   ├── llm_classifier.py
│   ├── models.py
│   ├── monitor.py
│   ├── policy.py
│   ├── research_dataset.py
│   ├── store.py
│   ├── task_executor.py
│   └── data/
│       ├── patients.json
│       └── research_dataset.json
├── web/
│   ├── index.html
│   ├── evals.html
│   ├── admin.html
│   ├── app.js
│   ├── evals.js
│   ├── security_console.js
│   └── styles.css
├── tests/
│   └── test_system.py
├── evaluate.py
├── run.py
└── README.md
```

## How It Works

The high-level flow is:

1. A user submits a message from the frontend.
2. The planner maps that message into a structured tool/action.
3. The selected detector mode evaluates the request.
4. The policy engine decides whether the request should proceed.
5. Approved requests reach the SQLite-backed fake EHR.
6. The system returns a response and may log incidents.

## Running the Project

### 1. Start the app

From the project root:

```powershell
py run.py
```

Then open:

- `http://127.0.0.1:8000` for the main interface
- `http://127.0.0.1:8000/evals.html` for the evaluation page

### 2. Run the evaluation suite

```powershell
py evaluate.py
```

### 3. Run the tests

```powershell
py -m unittest discover -s tests
```

## OpenAI API Usage

The LLM-only and hybrid modes can use the OpenAI API if an API key is available.

Set:

```powershell
$env:OPENAI_API_KEY="your_key_here"
```

Optional:

```powershell
$env:MEDGUARD_LLM_MODEL="gpt-4o-mini"
```

If `OPENAI_API_KEY` is not set, the system can still run locally, but LLM-backed classification will be unavailable.

