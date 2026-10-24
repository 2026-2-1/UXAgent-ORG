import asyncio
import unittest

from src.simulated_web_agent.main.model import AgentPolicy


class PolicyLifecycleTests(unittest.IsolatedAsyncioTestCase):
    async def test_close_waits_for_background_inference_task_cancellation(self):
        started = asyncio.Event()
        stopped = asyncio.Event()

        async def background():
            started.set()
            try:
                await asyncio.Event().wait()
            finally:
                await asyncio.sleep(0)
                stopped.set()

        policy = AgentPolicy.__new__(AgentPolicy)
        task = asyncio.create_task(background())
        policy.slow_loop_task = task
        await started.wait()
        await policy.close()
        self.assertTrue(task.cancelled())
        self.assertTrue(stopped.is_set())
        self.assertIsNone(policy.slow_loop_task)


if __name__ == "__main__":
    unittest.main()
