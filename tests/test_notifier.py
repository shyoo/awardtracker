import os
import sys
import unittest
from unittest import mock

# Ensure project root is in the python path
sys.path.append(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import notifier

# A typical Selenium failure: the selector comes back quoted as JSON.
SYNC_ERROR = (
    'Synchronization failed for Example Rewards: Message: no such element: '
    'Unable to locate element: {"method":"css selector","selector":"#balance"}'
)


@mock.patch("platform.system", return_value="Darwin")
class TestMacNotification(unittest.TestCase):
    def test_message_with_quotes_reaches_macos_unchanged(self, _system):
        macos = mock.MagicMock()
        with mock.patch.dict(sys.modules, {"macos": macos}):
            notifier.send_desktop_notification("Sync Failed", SYNC_ERROR)

        macos.notify.assert_called_once_with(SYNC_ERROR, title="Sync Failed")

    def test_notification_error_is_reported_not_raised(self, _system):
        macos = mock.MagicMock()
        macos.notify.side_effect = PermissionError("notifications are turned off")
        with mock.patch.dict(sys.modules, {"macos": macos}), \
                mock.patch("builtins.print") as printed:
            notifier.send_desktop_notification("Sync Failed", SYNC_ERROR)

        printed.assert_called_once()
        self.assertIn("notifications are turned off", printed.call_args.args[0])


if __name__ == "__main__":
    unittest.main()
