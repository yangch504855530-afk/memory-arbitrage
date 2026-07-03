from __future__ import annotations

from models import PriceObservation, utc_now_iso


class ManualCollector:
    """Builds observations from manually entered prices."""

    source = "manual"

    def collect(
        self,
        product_id: str,
        buy_price: float | None,
        sell_price: float | None,
        xianyu_listing_count: int | None = None,
        collected_at: str | None = None,
        buy_source: str = "",
        sell_source: str = "",
        raw_payload: str = "",
    ) -> PriceObservation:
        return PriceObservation(
            product_id=product_id,
            buy_price=buy_price,
            sell_price=sell_price,
            xianyu_listing_count=xianyu_listing_count,
            collected_at=collected_at or utc_now_iso(),
            source=self.source,
            buy_source=buy_source,
            sell_source=sell_source,
            raw_payload=raw_payload,
        )
