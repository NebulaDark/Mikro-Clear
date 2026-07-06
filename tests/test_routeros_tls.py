import ssl
import unittest

from mikroclear.routeros.ssl_context import build_routeros_ssl_context, make_routeros_ssl_wrapper


class FakeContext:
    def __init__(self):
        self.minimum_version = None
        self.maximum_version = None
        self.check_hostname = None
        self.verify_mode = None
        self.loaded_cafile = None
        self.ciphers = None
        self.options = 0
        self.wrap_calls = []

    def load_verify_locations(self, *, cafile):
        self.loaded_cafile = cafile

    def set_ciphers(self, value):
        self.ciphers = value

    def wrap_socket(self, sock, **kwargs):
        self.wrap_calls.append((sock, kwargs))
        return ("wrapped", sock, kwargs)


class RouterOsTlsTests(unittest.TestCase):
    def test_ca_verified_context_enables_hostname_checking(self):
        fake = FakeContext()

        context = build_routeros_ssl_context(
            cafile="/etc/mikroclear/certs/router-ca.crt",
            allow_self_signed=False,
            context_factory=lambda: fake,
        )

        self.assertIs(context, fake)
        self.assertEqual(fake.loaded_cafile, "/etc/mikroclear/certs/router-ca.crt")
        self.assertTrue(fake.check_hostname)
        self.assertEqual(fake.verify_mode, ssl.CERT_REQUIRED)
        self.assertEqual(fake.minimum_version, ssl.TLSVersion.TLSv1_2)
        self.assertEqual(fake.maximum_version, ssl.TLSVersion.TLSv1_2)

    def test_self_signed_mode_keeps_certificate_validation_disabled(self):
        fake = FakeContext()

        build_routeros_ssl_context(
            cafile="/missing.crt",
            allow_self_signed=True,
            context_factory=lambda: fake,
        )

        self.assertFalse(fake.check_hostname)
        self.assertEqual(fake.verify_mode, ssl.CERT_NONE)
        self.assertIsNone(fake.loaded_cafile)

    def test_ssl_wrapper_injects_routeros_server_hostname(self):
        fake = FakeContext()
        wrapper = make_routeros_ssl_wrapper(fake, "192.168.10.1")

        result = wrapper("socket-object")

        self.assertEqual(result[0], "wrapped")
        self.assertEqual(fake.wrap_calls[0][1]["server_hostname"], "192.168.10.1")

    def test_ssl_wrapper_preserves_explicit_server_hostname(self):
        fake = FakeContext()
        wrapper = make_routeros_ssl_wrapper(fake, "192.168.10.1")

        wrapper("socket-object", server_hostname="r1.21port.ru")

        self.assertEqual(fake.wrap_calls[0][1]["server_hostname"], "r1.21port.ru")


if __name__ == "__main__":
    unittest.main()
