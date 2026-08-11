window.GADE_SITE_DATA = {
  project: {
    name: "GADE CUA Evolve",
    author: "YOUR NAME / Author TBD",
    github: "https://github.com/GADE-Tech/GADE-CUA-Evolve",
    description: "A composable computer-use agent runtime where ARM checks real desktop outcomes and turns evidence into stop-or-retry decisions."
  },
  heroScores: [
    {
      label: "OSWorld 1.0",
      detail: "Project verified · Gemini 3.1 Pro",
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
  trajectory: {
    id: "gimp-open-vignette",
    instruction: "Help me open up the Vignette filter window.",
    frames: [
      {
        step: 0,
        image: "assets/trajectories/gimp-open-vignette/initial.webp",
        actionType: "initial",
        actionLabel: "Initial desktop state"
      },
      {
        step: 1,
        image: "assets/trajectories/gimp-open-vignette/step-01.webp",
        actionType: "click",
        actionLabel: "Keep the image's embedded color profile",
        point: { x: 0.5791666667, y: 0.6490740741 }
      },
      {
        step: 2,
        image: "assets/trajectories/gimp-open-vignette/step-02.webp",
        actionType: "click",
        actionLabel: "Open the Filters menu",
        point: { x: 0.2447916667, y: 0.0712962963 }
      },
      {
        step: 3,
        image: "assets/trajectories/gimp-open-vignette/step-03.webp",
        actionType: "click",
        actionLabel: "Choose Light and Shadow",
        point: { x: 0.2947916667, y: 0.2453703704 }
      },
      {
        step: 4,
        image: "assets/trajectories/gimp-open-vignette/step-04.webp",
        actionType: "click",
        actionLabel: "Reveal the Light and Shadow submenu",
        point: { x: 0.2911458333, y: 0.2462962963 }
      },
      {
        step: 5,
        image: "assets/trajectories/gimp-open-vignette/step-05.webp",
        actionType: "click",
        actionLabel: "Open the Vignette filter window",
        point: { x: 0.4239583333, y: 0.4425925926 }
      }
    ],
    arm: {
      episode: 1,
      checklist: [
        "GIMP is running with an active image loaded.",
        "The Vignette filter window is open and visible."
      ],
      verdict: "success",
      rationale: "The active image and the Vignette filter window are both visible in the final desktop state.",
      continue: false
    }
  },
  sources: {
    experiment: "Project Q2 experiment summary · 2026",
    disclaimer: "Project experiment results. Not a claim about a live official leaderboard."
  }
};
