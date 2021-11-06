import unittest
from unittest import IsolatedAsyncioTestCase
from utils import Database

events = []


class DbTest(IsolatedAsyncioTestCase):

    def setUp(self):
        events.append("setUp")

    async def asyncSetUp(self):
        events.append("asyncSetUp")

    async def test_response(self):
        events.append("test_response")
        response = await Database.init()
        print(response)
        # self.assertEqual(response.status_code, 200)
        self.addAsyncCleanup(self.on_cleanup)

    def tearDown(self):
        events.append("tearDown")

    async def asyncTearDown(self):
        events.append("asyncTearDown")

    async def on_cleanup(self):
        events.append("cleanup")


if __name__ == "__main__":
    unittest.main()
