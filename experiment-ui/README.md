# Vue 3 + TypeScript + Vite

This template should help get you started developing with Vue 3 and TypeScript in Vite. The template uses Vue 3 `<script setup>` SFCs, check out the [script setup docs](https://v3.vuejs.org/api/sfc-script-setup.html#sfc-script-setup) to learn more.

Learn more about the recommended Project Setup and IDE Support in the [Vue Docs TypeScript Guide](https://vuejs.org/guide/typescript/overview.html#project-setup).

## Live run monitor

Start the API from the repository root with `.venv/Scripts/python.exe -m src.simulated_web_agent.main.app`, and the UI from this directory with `npm run dev`.

Step 3's **Confirm and Run** opens a separate monitor window. If popups are blocked, use the progress link shown above the wizard. The monitor polls the backend every second and shows each persona's generation, queue, browser actions, survey, completion, and errors. Browser action progress measures actions taken against the configured maximum; a task can finish before reaching that maximum.

`POST /run` returns HTTP 202 with a `run_id` immediately. `GET /progress?run_id=...` reads that run; omitting the ID reads the latest run. Reloading the monitor retains its run ID. The API permits one active study at a time because the pipeline shares model configuration and output files. Run state is held in the API process and is cleared when it restarts; use one API process.

Validation from the repository root:

```powershell
.venv/Scripts/python.exe -m unittest discover -s tests -v
# Run npm run build in experiment-ui first:
.venv/Scripts/python.exe scripts/check_progress_ui.py
```

The browser check uses fixture API responses and does not launch a real study or call an LLM.
