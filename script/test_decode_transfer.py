
import unittest
from copy import deepcopy

from script.decode_transfer_fixture import decode_transfer, log

class TestDecodeTransfer(unittest.TestCase):
    def test_rejects_invalid_address_topic_prefix(self):
        for index, name in ((1, "sender"), (2, "receiver")):
            with self.subTest(topic=name):
                bad_log = deepcopy(log)
                bad_log["topics"][index] = "zz" + "11" * 32
                with self.assertRaisesRegex(ValueError, f"^{name} topic must start with 0x$"):
                    decode_transfer(bad_log)

    def test_rejects_non_hex_address_topics(self):
        for index, name in ((1, "sender"), (2, "receiver")):
            with self.subTest(topic=name):
                bad_log = deepcopy(log)
                bad_log["topics"][index] = "0x" + "zz" * 32
                with self.assertRaisesRegex(
                    ValueError, f"^{name} topic must contain only hex characters$"
                ):
                    decode_transfer(bad_log)

    def test_rejects_wrong_event_signature(self):
        bad_log = deepcopy(log)
        bad_log["topics"][0] = "0x" + "00" * 32

        with self.assertRaisesRegex(
            ValueError,
            r"^topics\[0\] must be Transfer signature$"
        ):            
            decode_transfer(bad_log)

    def test_rejects_wrong_event_sender(self):
        bad_log = deepcopy(log)
        bad_log["topics"][1] = "0x" + "0" * 24 + "11" * 22
        
        with self.assertRaisesRegex(
            ValueError,
            r"^Invalid sender topic length$"
        ):
            decode_transfer(bad_log)


    def test_rejects_wrong_event_receiver(self):
        bad_log = deepcopy(log)
        bad_log["topics"][2] = "0x" + "0" * 24 + "22" * 22

        with self.assertRaisesRegex(
            ValueError,
            r"^Invalid receiver topic length$"
        ):
            decode_transfer(bad_log)

    def test_rejects_wrong_event_data(self):
        bad_log = deepcopy(log)
        bad_log["data"] = "0x" + "20000000000001".zfill(66)

        with self.assertRaisesRegex(
            ValueError,
            r"^Invalid data topic length$"
        ):
            decode_transfer(bad_log)

    def test_rejects_missing_receiver_topic(self):
        bad_log = deepcopy(log)
        bad_log["topics"].pop()

        with self.assertRaisesRegex(
            ValueError,
            r"^Transfer must have 3 topics$"
        ):
            decode_transfer(bad_log)


    def test_rejects_non_hex_data(self):
        bad_log = deepcopy(log)
        bad_log["data"] = "0x" + "zz" * 32

        with self.assertRaisesRegex(
            ValueError,
            r"^Data must contain only hex characters$"
        ):
            decode_transfer(bad_log)


    def test_decodes_valid_amounts(self):
        for value in (0, 2**53 + 1, 2**256 - 1):
            with self.subTest(value=value):
                valid_log = deepcopy(log)
                valid_log["data"] = "0x" + format(value, "064x")

                result = decode_transfer(valid_log)

                self.assertEqual(result, {
                    "from": {"hash": "0x" + "11" * 20},
                    "to": {"hash": "0x" + "22" * 20},
                    "transaction_hash": valid_log["transactionHash"],
                    "total": {"value": str(value)},
                })


