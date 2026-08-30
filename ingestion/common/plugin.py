"""Shared interface every marketplace ingestion plugin implements.

A plugin's only job is: poll its marketplace, validate/normalize the response
into NormalizedListing, and hand them back. It has no knowledge of Kafka,
Postgres, skin_variants, or float-bucket resolution — that separation is what
lets a second marketplace (Skinport, or others) drop in without touching the
consolidator (see plan Section 3/4).
"""

from __future__ import annotations

import abc

from ingestion.common.schema import NormalizedListing


class MarketplacePlugin(abc.ABC):
    marketplace: str

    @abc.abstractmethod
    def fetch_listings(self) -> list[NormalizedListing]:
        """One poll cycle: call the marketplace API and return normalized listings.

        Implementations are responsible for their own pagination within a
        single call, and for raising on unrecoverable errors — the runner
        treats an exception here as a failed poll and retries on the next tick.
        """
        raise NotImplementedError
