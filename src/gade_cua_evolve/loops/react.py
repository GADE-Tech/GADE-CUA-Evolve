"""OSWorld-style ReAct execution loop."""

from __future__ import annotations

import time

from gade_cua_evolve.config import TaskSpec

from .base import AgentLoop, RunResult


class ReActLoop(AgentLoop):
    def run(self, task: TaskSpec) -> RunResult:
        done = False
        predict_steps = 0
        action_steps = 0
        score = 0.0
        recording = False
        try:
            observation = self.env.reset(task)
            if self.recorder:
                self.recorder.record_initial(observation)
            for agent in self.agents.values():
                agent.reset()
            if self.config.record_video:
                self.env.start_recording()
                recording = True
            while not done and predict_steps < self.config.max_steps:
                name, agent = self.select_agent(predict_steps, observation)
                predicted = agent.predict(task.instruction, observation)
                actions = predicted.actions or ["WAIT"]
                for action in actions:
                    outcome = self.env.step(action, self.config.sleep_after_action)
                    agent.on_action_result(predicted, action, outcome)
                    observation = outcome.observation
                    done = outcome.done
                    action_steps += 1
                    if self.recorder:
                        self.recorder.record(
                            predict_step=predict_steps + 1,
                            agent_name=name,
                            raw_response=predicted.raw_response,
                            thought=predicted.thought,
                            low_level_instruction=predicted.low_level_instruction,
                            agent_metadata=predicted.metadata,
                            action=action,
                            observation=observation,
                            done=done,
                            info=outcome.info,
                        )
                    if done:
                        break
                predict_steps += 1
            if self.config.settle_seconds:
                time.sleep(self.config.settle_seconds)
            score = self.env.evaluate()
        finally:
            try:
                if recording:
                    directory = self.recorder.directory if self.recorder else self.config.output_dir
                    directory.mkdir(parents=True, exist_ok=True)
                    self.env.stop_recording(str(directory / "recording.mp4"))
            finally:
                try:
                    self.env.close()
                finally:
                    if self.recorder:
                        self.recorder.finish(score=score, done=done, predict_steps=predict_steps)
        return RunResult(
            task=task,
            score=score,
            done=done,
            predict_steps=predict_steps,
            action_steps=action_steps,
            output_dir=str(self.recorder.directory) if self.recorder else None,
        )
