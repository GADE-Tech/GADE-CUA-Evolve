window.GADE_SITE_DATA = {
  project: {
    name: "GADE CUA Evolve",
    author: "Author One · Author Two · Author Three · Author Four",
    github: "https://github.com/GADE-Tech/GADE-CUA-Evolve",
    description: "A self-evolving computer-use agent and scalable OSWorld rollout runtime where Planner, Grounder, Coder, and ARM act, verify, and improve from real desktop outcomes."
  },
  heroScores: [
    {
      label: "OSWorld 1.0",
      detail: "Self-Evolve · Gemini 3.1 Pro",
      value: 79.6,
      precision: 1
    },
    {
      label: "Windows Agent Arena",
      detail: "Best Self-Evolve · Gemini 3.1",
      value: 72.54,
      precision: 2
    }
  ],
  benchmarks: {
    osworld: {
      title: "OSWorld 1.0",
      href: "https://github.com/xlang-ai/OSWorld",
      note: "Success rate · CUA (GUI + Coding)",
      models: [
        { name: "Gemini 3.1 Pro", baseline: 76.0, evolve: 79.6 },
        { name: "Qwen 3.5-27B", baseline: 63.4, evolve: 68.8 }
      ]
    },
    windows: {
      title: "Windows Agent Arena",
      href: "https://github.com/microsoft/WindowsAgentArena",
      note: "Success rate · 152 tasks",
      models: [
        { name: "Gemini 3.1", baseline: 66.74, evolve: 72.54 },
        { name: "Qwen 3.5-27B", baseline: 51.2, evolve: 56.5 }
      ],
      gtJudge: 75.47
    },
    guiCoding: [
      { label: "GUI only", value: 72.5 },
      { label: "GUI + Coding", value: 76.0 }
    ],
    scaling: [
      { method: "Baseline", rollouts: 316, score: 66.5, series: "baseline" },
      { method: "ARM", rollouts: 470, score: 73.7, series: "arm" },
      { method: "Wide · BoN≈5", rollouts: 1580, score: 75.0, series: "wide" }
    ]
  },
  diagnostics: {
    osworld: {
      title: "OSWorld ARM diagnosis",
      metrics: [
        ["Precision", "87.63%"],
        ["Recall", "83.50%"],
        ["F1", "85.52%"]
      ],
      matrix: { tp: 248, fn: 49, fp: 35, tn: 29 }
    },
    windows: {
      title: "Windows Agent Arena ARM diagnosis",
      metrics: [
        ["Precision", "78%"],
        ["Recall", "100%"],
        ["F1", "88%"],
        ["Accuracy", "82%"]
      ],
      matrix: { tp: 101, fn: 0, fp: 28, tn: 23 }
    }
  },
  loopDemo: {
    interval: 2600,
    phases: [
      {
        phase: "TASK",
        episode: "EPISODE 01",
        title: "Add a Profit column and calculate Sales − COGS.",
        detail: "The workbook starts without the requested result.",
        image: "assets/trajectories/osworld-profit/initial.webp",
        tone: "actor"
      },
      {
        phase: "ACTOR · CODE",
        episode: "EPISODE 01",
        title: "Write Profit formulas into D1:D11.",
        detail: "The Planner chooses a coding action; the GUI now looks correct.",
        image: "assets/trajectories/osworld-profit/profit-added.webp",
        tone: "actor"
      },
      {
        phase: "ACTOR · DONE",
        episode: "EPISODE 01",
        title: "Stop: the requested values are visible.",
        detail: "The Actor declares success from the current desktop state.",
        image: "assets/trajectories/osworld-profit/profit-added.webp",
        tone: "actor"
      },
      {
        phase: "ARM · CHECK",
        episode: "EPISODE 01",
        title: "Not completed: the saved file still contains null.",
        detail: "ARM checks persistent evidence, not just the visible spreadsheet.",
        image: "assets/trajectories/osworld-profit/profit-added.webp",
        tone: "arm"
      },
      {
        phase: "FEEDBACK ↺",
        episode: "STOP → RETRY",
        title: "The formulas are correct, but the workbook was not saved.",
        detail: "This evidence is appended to the next Actor episode.",
        image: "assets/trajectories/osworld-profit/profit-added.webp",
        tone: "arm"
      },
      {
        phase: "ACTOR · HOTKEY",
        episode: "EPISODE 02",
        title: "Apply feedback: press Ctrl + S.",
        detail: "The next episode performs only the missing action.",
        image: "assets/trajectories/osworld-profit/saved.webp",
        tone: "actor"
      },
      {
        phase: "STOP · SUCCESS",
        episode: "EPISODE 02",
        title: "Saved workbook verified. End the loop.",
        detail: "The native evaluator returns 1.0.",
        image: "assets/trajectories/osworld-profit/saved.webp",
        tone: "success"
      }
    ]
  },
  trajectories: [
    {
      id: "osworld-profit",
      tabLabel: "Profit column",
      environment: "OSWorld · Ubuntu · Calc",
      title: "Add and save a Profit column.",
      instruction: "Add a new column named ‘Profit’ next to ‘COGS’ and calculate Sales minus COGS for every week.",
      taskId: "1e8df695-bd1b-45b3-b557-e7d599cf7597",
      frames: [
        {
          image: "assets/trajectories/osworld-profit/initial.webp",
          episode: 1,
          actionType: "task",
          actionLabel: "WeeklySales.xlsx opens with Week, Sales, and COGS columns."
        },
        {
          image: "assets/trajectories/osworld-profit/profit-added.webp",
          episode: 1,
          actionType: "code",
          actionLabel: "Actor writes the Profit header and formulas into D1:D11."
        },
        {
          image: "assets/trajectories/osworld-profit/profit-added.webp",
          episode: 1,
          actionType: "done",
          actionLabel: "Actor returns DONE because every requested value is visible."
        },
        {
          image: "assets/trajectories/osworld-profit/profit-added.webp",
          episode: 1,
          actionType: "arm",
          actionLabel: "ARM inspects the persisted workbook and finds the Profit cells are null.",
          arm: {
            verdict: "NOT COMPLETED",
            tone: "retry",
            checklist: ["D1 is exactly ‘Profit’.", "D2:D11 contain Sales − COGS."],
            rationale: "The GUI is correct, but the changes were never saved to WeeklySales.xlsx.",
            next: "RETRY WITH FEEDBACK"
          }
        },
        {
          image: "assets/trajectories/osworld-profit/saved.webp",
          episode: 2,
          actionType: "hotkey",
          actionLabel: "Episode 2 follows ARM feedback and presses Ctrl + S."
        },
        {
          image: "assets/trajectories/osworld-profit/saved.webp",
          episode: 2,
          actionType: "success",
          actionLabel: "The saved workbook passes the native evaluator with a 1.0 score.",
          arm: {
            verdict: "SUCCESS",
            tone: "success",
            checklist: ["Profit formulas are present.", "The workbook changes persist on disk."],
            rationale: "The missing save action was corrected in the feedback episode.",
            next: "STOP"
          }
        }
      ]
    },
    {
      id: "waa-center-heading",
      tabLabel: "Center heading",
      environment: "Windows Agent Arena · Windows · Writer",
      title: "Center-align a document heading.",
      instruction: "Help me center align the heading in LibreOffice.",
      taskId: "3ef2b351-8a84-4ff2-8724-d86eae9b842e-WOS",
      frames: [
        {
          image: "assets/trajectories/waa-center-heading/initial.webp",
          episode: 1,
          actionType: "task",
          actionLabel: "Actor scrolls to the heading and places the cursor in it."
        },
        {
          image: "assets/trajectories/waa-center-heading/right-aligned.webp",
          episode: 1,
          actionType: "click",
          actionLabel: "Grounding misses the center icon and clicks Align Right."
        },
        {
          image: "assets/trajectories/waa-center-heading/right-aligned.webp",
          episode: 1,
          actionType: "done",
          actionLabel: "Actor saves the document and incorrectly returns DONE."
        },
        {
          image: "assets/trajectories/waa-center-heading/right-aligned.webp",
          episode: 1,
          actionType: "arm",
          actionLabel: "ARM reads the saved paragraph alignment as RIGHT (2).",
          arm: {
            verdict: "NOT COMPLETED",
            tone: "retry",
            checklist: ["A LibreOffice document is open.", "The heading is center-aligned."],
            rationale: "The right-align toolbar button is active and the saved file confirms RIGHT alignment.",
            next: "RETRY WITH FEEDBACK"
          }
        },
        {
          image: "assets/trajectories/waa-center-heading/centered.webp",
          episode: 2,
          actionType: "hotkey",
          actionLabel: "Episode 2 uses Ctrl + E to center the heading, then saves."
        },
        {
          image: "assets/trajectories/waa-center-heading/centered.webp",
          episode: 2,
          actionType: "success",
          actionLabel: "The centered heading persists and the task receives a 1.0 score.",
          arm: {
            verdict: "SUCCESS",
            tone: "success",
            checklist: ["The document remains open.", "The saved heading is center-aligned."],
            rationale: "ARM feedback changed the next action from imprecise clicking to an exact shortcut.",
            next: "STOP"
          }
        }
      ]
    }
  ],
  sources: {
    experiment: "Project Q2 experiment summary · 2026",
    disclaimer: "Project experiment results. Not a claim about a live official leaderboard."
  }
};
