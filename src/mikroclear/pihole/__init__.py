"""Pi-hole REST integration for Mikro-Clear."""

from mikroclear.pihole.client import PiholeClient, PiholeClientError

__all__ = ["PiholeClient", "PiholeClientError"]
