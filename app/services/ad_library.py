"""Fase de anúncios de concorrentes — via TikTok Commercial Content API (só Europa)."""
import re
from datetime import datetime
from typing import Optional

import pandas as pd
from sqlalchemy.orm import Session

from app.adlib_client import adlib_client
from app.models import CompetitorAd


def get_client_token() -> str:
    """Token de app (client_credentials) — não depende de nenhum vendedor conectado."""
    return adlib_client.get_client_token()["access_token"]


def reach_to_number(label: str) -> float:
    """'11K' -> 11000.0, '2M' -> 2_000_000.0. Só pra poder ordenar; a API já entrega em faixas."""
    if not label:
        return 0.0
    match = re.match(r"([\d.]+)([KMB]?)", label.strip().upper())
    if not match:
        return 0.0
    value, unit = match.groups()
    multiplier = {"": 1, "K": 1_000, "M": 1_000_000, "B": 1_000_000_000}[unit]
    return float(value) * multiplier


def search_and_track(db: Session, access_token: str, search_term: str, country_code: Optional[str] = None, max_count: int = 20) -> int:
    """Busca anúncios na Ad Library e grava/atualiza localmente. Retorna quantos foram gravados."""
    data = adlib_client.query_ads(access_token, search_term=search_term, country_code=country_code, max_count=max_count)
    ads = data.get("ads", [])

    saved = 0
    for entry in ads:
        ad = entry.get("ad", {})
        advertiser = entry.get("advertiser", {})
        tt_ad_id = str(ad.get("id"))

        existing = db.query(CompetitorAd).filter(CompetitorAd.tt_ad_id == tt_ad_id).one_or_none()
        if existing is None:
            existing = CompetitorAd(tt_ad_id=tt_ad_id)
            db.add(existing)

        videos = ad.get("videos") or []
        images = ad.get("image_urls") or []

        existing.search_term = search_term
        existing.country_code = country_code or ""
        existing.advertiser_business_id = str(advertiser.get("business_id") or "") or None
        existing.advertiser_name = advertiser.get("business_name", "")
        existing.status = ad.get("status", "")
        existing.first_shown_date = str(ad.get("first_shown_date") or "")
        existing.last_shown_date = str(ad.get("last_shown_date") or "")
        existing.reach_label = (ad.get("reach") or {}).get("unique_user_seen", "")
        existing.video_url = videos[0]["url"] if videos else ""
        existing.thumbnail_url = images[0] if images else ""
        existing.captured_at = datetime.utcnow()
        saved += 1

    db.commit()
    return saved


def list_tracked_ads(db: Session, search_term: Optional[str] = None) -> pd.DataFrame:
    query = db.query(CompetitorAd)
    if search_term:
        query = query.filter(CompetitorAd.search_term == search_term)

    rows = [
        {
            "id": a.id,
            "advertiser_name": a.advertiser_name or "(anunciante não informado)",
            "search_term": a.search_term,
            "country_code": a.country_code,
            "status": a.status,
            "first_shown_date": a.first_shown_date,
            "last_shown_date": a.last_shown_date,
            "reach_label": a.reach_label,
            "reach_value": reach_to_number(a.reach_label),
            "thumbnail_url": a.thumbnail_url,
            "video_url": a.video_url,
        }
        for a in query.order_by(CompetitorAd.captured_at.desc()).all()
    ]
    df = pd.DataFrame(rows)
    if not df.empty:
        df = df.sort_values("reach_value", ascending=False).reset_index(drop=True)
    return df
