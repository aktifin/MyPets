"""Customer-facing portal experience APIs.

The user portal must never require people to know internal template IDs or version
triples. This module projects published asset releases into simple pet presets and
keeps a bundled starter preset available before content operations publish anything.
"""

from __future__ import annotations

from typing import Annotated, Literal

from fastapi import APIRouter, Depends
from pydantic import BaseModel
from sqlalchemy import select
from sqlalchemy.orm import Session

from .api import get_session, require_account
from .models import PetAssetRelease, PetTemplate
from .security import Principal

portal_experience_router = APIRouter(prefix="/api/v1/portal", tags=["user-portal"])


class PetPresetView(BaseModel):
    preset_id: str
    display_name: str
    species: str
    description: str
    template_id: str
    template_version: str
    identity_version: str
    asset_version: str
    source: Literal["bundled", "published"]
    icon: str


_BUNDLED_PRESET = PetPresetView(
    preset_id="bundled:official.cat.white:1.0.0:1.0.0",
    display_name="云朵白猫",
    species="cat",
    description="温和、亲近，适合作为第一只桌面宠物。",
    template_id="official.cat.white",
    template_version="1.0.0",
    identity_version="1.0.0",
    asset_version="1.0.0",
    source="bundled",
    icon="🐱",
)


def _species_icon(species: str) -> str:
    return {
        "cat": "🐱",
        "dog": "🐶",
        "rabbit": "🐰",
        "hamster": "🐹",
        "bird": "🐦",
        "fish": "🐟",
    }.get(species.lower(), "🐾")


@portal_experience_router.get("/pet-presets", response_model=list[PetPresetView])
def list_pet_presets(
    _principal: Annotated[Principal, Depends(require_account)],
    session: Annotated[Session, Depends(get_session)],
) -> list[PetPresetView]:
    rows = session.execute(
        select(PetAssetRelease, PetTemplate)
        .outerjoin(PetTemplate, PetTemplate.template_code == PetAssetRelease.template_code)
        .order_by(PetAssetRelease.created_at.desc(), PetAssetRelease.id.desc())
    ).all()

    presets: list[PetPresetView] = []
    seen_templates: set[str] = set()
    for release, template in rows:
        if release.template_code in seen_templates:
            continue
        seen_templates.add(release.template_code)
        species = template.species if template is not None else "pet"
        presets.append(
            PetPresetView(
                preset_id=(
                    f"published:{release.template_code}:"
                    f"{release.identity_version}:{release.asset_version}"
                ),
                display_name=(template.display_name if template is not None else release.template_code),
                species=species,
                description=(
                    template.description
                    if template is not None and template.description
                    else "已发布并可用于桌面端的宠物形象。"
                ),
                template_id=release.template_code,
                template_version=release.template_version,
                identity_version=release.identity_version,
                asset_version=release.asset_version,
                source="published",
                icon=_species_icon(species),
            )
        )

    if _BUNDLED_PRESET.template_id not in seen_templates:
        presets.insert(0, _BUNDLED_PRESET)
    return presets
