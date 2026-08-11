"""Episode-based actor/reward-agent feedback loop."""

from __future__ import annotations

from gade_cua_evolve.config import TaskSpec
from gade_cua_evolve.reward import TrajectoryItem, VerificationPlan

from .base import AgentLoop, RunResult


class AgenticFeedbackLoop(AgentLoop):
    """Run actor segments, optional ARM verification, and optional human steering."""

    def run(self, task: TaskSpec) -> RunResult:
        done = False
        status = "running"
        score: float | None = None
        predict_steps = 0
        action_steps = 0
        episodes = 0
        arm_verdict: str | None = None
        arm_feedback: list[str] = []
        trajectory: list[TrajectoryItem] = []
        recording = False
        evaluate_requested = self.evaluate_at_end
        plan: VerificationPlan | None = None
        observation = None
        try:
            observation = self.env.reset(task)
            initial = observation
            if self.recorder:
                self.recorder.record_initial(observation)
            for agent in self.agents.values():
                agent.reset()
            if self.config.record_video:
                self.env.start_recording()
                recording = True
            self.controller.emit("started", task.instruction)
            if self.recorder:
                self.recorder.record_event("started", task.instruction)
            if self.reward_model:
                try:
                    plan = self.reward_model.plan(
                        task.public_view(),
                        initial,
                        (self.recorder.directory if self.recorder else self.config.output_dir) / "arm",
                    )
                    self.controller.emit("arm_plan", "Verification checklist prepared")
                    if self.recorder:
                        self.recorder.record_event(
                            "arm_plan", "Verification checklist prepared", checklist=plan.checklist
                        )
                except Exception as exc:  # noqa: BLE001
                    status = "arm_error"
                    arm_verdict = "error"
                    arm_feedback.append(f"ARM planning failed: {type(exc).__name__}: {exc}")
            arm_config = self.reward_model.config if self.reward_model else None
            max_episodes = arm_config.max_episodes if arm_config else max(1, self.config.max_steps)
            segment_limit = (
                arm_config.actor_steps_per_episode if arm_config else self.config.max_steps
            )
            while status == "running" and predict_steps < self.config.max_steps:
                if episodes >= max_episodes or not self.controller.checkpoint():
                    status = "cancelled" if self.controller.cancelled else "max_episodes"
                    break
                episodes += 1
                terminal_requested = False
                for _ in range(segment_limit):
                    if predict_steps >= self.config.max_steps or not self.controller.checkpoint():
                        break
                    name, agent = self.select_agent(predict_steps, observation)
                    for feedback in self.controller.drain_feedback():
                        agent.on_feedback(feedback)
                        if self.recorder:
                            self.recorder.record_event("human_feedback", feedback)
                    predicted = agent.predict(task.instruction, observation)
                    predict_steps += 1
                    self.controller.emit(
                        "agent_step",
                        predicted.low_level_instruction,
                        thought=predicted.thought,
                        predict_step=predict_steps,
                    )
                    actions = predicted.actions or ["WAIT"]
                    for action in actions:
                        if action in {"DONE", "FAIL"}:
                            terminal_requested = True
                            trajectory.append(
                                TrajectoryItem(
                                    predict_steps,
                                    action,
                                    predicted.thought,
                                    observation.screenshot,
                                )
                            )
                            self._record(
                                predict_steps, name, predicted, action, observation, False, {}
                            )
                            break
                        outcome = self.env.step(action, self.config.sleep_after_action)
                        agent.on_action_result(predicted, action, outcome)
                        observation = outcome.observation
                        action_steps += 1
                        trajectory.append(
                            TrajectoryItem(
                                predict_steps,
                                action,
                                predicted.thought,
                                observation.screenshot,
                            )
                        )
                        self._record(
                            predict_steps,
                            name,
                            predicted,
                            action,
                            observation,
                            outcome.done,
                            outcome.info,
                        )
                        self.controller.emit(
                            "action",
                            action,
                            action_step=action_steps,
                            screenshot=observation.screenshot,
                        )
                        if outcome.done:
                            terminal_requested = True
                            break
                    if terminal_requested:
                        break

                if self.reward_model and plan:
                    episode_dir = (
                        self.recorder.directory if self.recorder else self.config.output_dir
                    ) / "arm" / f"episode_{episodes:02d}"
                    try:
                        verification = self.reward_model.verify(
                            task=task.public_view(),
                            plan=plan,
                            initial=initial,
                            current=observation,
                            trajectory=trajectory,
                            env=self.env,
                            directory=episode_dir,
                        )
                    except Exception as exc:  # noqa: BLE001
                        status = "arm_error"
                        arm_verdict = "error"
                        arm_feedback.append(f"ARM verification failed: {type(exc).__name__}: {exc}")
                        break
                    observation = verification.observation or observation
                    arm_verdict = verification.verdict
                    arm_feedback.append(verification.feedback)
                    self.controller.emit(
                        "arm_verdict",
                        verification.feedback,
                        verdict=verification.verdict,
                        episode=episodes,
                    )
                    if self.recorder:
                        self.recorder.record_event(
                            "arm_verdict",
                            verification.feedback,
                            verdict=verification.verdict,
                            episode=episodes,
                        )
                    if verification.verdict == "failed":
                        for agent in self.agents.values():
                            agent.on_feedback(verification.feedback)
                        continue
                    if verification.verdict == "error":
                        status = "arm_error"
                        break
                    status = "completed" if verification.verdict == "success" else "infeasible"
                    done = True
                elif terminal_requested:
                    status = "completed"
                    done = True
                else:
                    continue

                decision = self.controller.request_completion(
                    "Agent believes the task is complete. Accept, continue, evaluate, or stop."
                )
                if self.recorder:
                    self.recorder.record_event("completion_decision", decision)
                if decision == "continue":
                    done = False
                    status = "running"
                    for agent in self.agents.values():
                        agent.on_feedback("The user asked you to continue checking and improving the task.")
                    continue
                if decision == "evaluate":
                    evaluate_requested = True
                if decision == "stop":
                    status = "cancelled"
                break

            if status == "running":
                status = "cancelled" if self.controller.cancelled else "max_steps"
            if evaluate_requested:
                if not task.has_native_evaluator:
                    raise ValueError("Native evaluation requires a task with an OSWorld evaluator")
                score = self.env.evaluate()
                self.controller.emit("native_score", f"Native evaluator score: {score}", score=score)
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
                        self.recorder.finish(
                            score=score,
                            done=done,
                            predict_steps=predict_steps,
                            status=status,
                            arm_verdict=arm_verdict,
                            arm_feedback=arm_feedback,
                            episodes=episodes,
                        )
        return RunResult(
            task=task,
            score=score,
            done=done,
            predict_steps=predict_steps,
            action_steps=action_steps,
            output_dir=str(self.recorder.directory) if self.recorder else None,
            status=status,
            arm_verdict=arm_verdict,
            arm_feedback=arm_feedback,
            episodes=episodes,
        )

    def _record(self, predict_step, name, predicted, action, observation, done, info) -> None:
        if not self.recorder:
            return
        self.recorder.record(
            predict_step=predict_step,
            agent_name=name,
            raw_response=predicted.raw_response,
            thought=predicted.thought,
            low_level_instruction=predicted.low_level_instruction,
            agent_metadata=predicted.metadata,
            action=action,
            observation=observation,
            done=done,
            info=info,
        )
