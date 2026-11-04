import re

from fastapi import APIRouter, Depends, File, HTTPException, Response, UploadFile, status
from sqlalchemy import select
from sqlalchemy.orm import Session

from ..config import get_settings
from ..database import get_db
from ..deps import get_current_user
from ..models import Agency, Client, User, new_domain_token
from ..schemas import AgencyOut, AgencyUpdate, ClientDomainSet, WorkspaceDomainOut
from ..services import dns as dns_service
from ..services import workspace_domain
from ..slugs import slugify


router = APIRouter(prefix="/agency", tags=["Agency"])
MAX_LOGO_BYTES = 2 * 1024 * 1024
ALLOWED_LOGO_TYPES = {"image/png", "image/jpeg", "image/webp", "image/svg+xml"}


def present(agency: Agency) -> AgencyOut:
    """The agency plus the deployment's store links, which live in settings
    rather than on the row: every deployment publishes one app, not one per
    agency."""
    settings = get_settings()
    out = AgencyOut.model_validate(agency)
    out.ios_app_url = (settings.portal_ios_app_url or "").strip() or None
    out.android_app_url = (settings.portal_android_app_url or "").strip() or None
    return out


@router.get("", response_model=AgencyOut)
def get_agency(user: User = Depends(get_current_user)):
    return present(user.agency)


@router.patch("", response_model=AgencyOut)
def update_agency(
    payload: AgencyUpdate,
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user),
):
    agency = user.agency
    values = payload.model_dump(exclude_unset=True)
    if "slug" in values and values["slug"]:
        candidate = slugify(values["slug"])
        if db.scalar(select(Agency).where(Agency.slug == candidate, Agency.id != agency.id)):
            raise HTTPException(status_code=409, detail="That identifier is already in use")
        values["slug"] = candidate
    if "brand_color" in values and not re.fullmatch(r"#[0-9a-fA-F]{6}", values["brand_color"] or ""):
        raise HTTPException(status_code=400, detail="The color must use the #075985 format")
    for key, value in values.items():
        setattr(agency, key, value)
    db.commit()
    db.refresh(agency)
    return present(agency)


@router.post("/logo", response_model=AgencyOut)
async def upload_logo(
    file: UploadFile = File(...),
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user),
):
    if file.content_type not in ALLOWED_LOGO_TYPES:
        raise HTTPException(status_code=400, detail="Use a PNG, JPG, WebP or SVG logo")
    data = await file.read(MAX_LOGO_BYTES + 1)
    if len(data) > MAX_LOGO_BYTES:
        raise HTTPException(status_code=413, detail="The logo exceeds the 2 MB limit")
    user.agency.logo_data = data
    user.agency.logo_mime = file.content_type
    db.commit()
    db.refresh(user.agency)
    return present(user.agency)


@router.get("/logo")
def get_logo(user: User = Depends(get_current_user)):
    agency = user.agency
    if not agency.logo_data or not agency.logo_mime:
        raise HTTPException(status_code=404, detail="The agency does not have a logo yet")
    return Response(content=agency.logo_data, media_type=agency.logo_mime, headers={"Cache-Control": "no-store"})


@router.delete("/logo", status_code=status.HTTP_204_NO_CONTENT)
def delete_logo(db: Session = Depends(get_db), user: User = Depends(get_current_user)):
    user.agency.logo_data = None
    user.agency.logo_mime = None
    db.commit()
    return Response(status_code=status.HTTP_204_NO_CONTENT)


@router.get("/domain", response_model=WorkspaceDomainOut)
def get_workspace_domain(check: bool = False, user: User = Depends(get_current_user)):
    return workspace_domain.describe(user.agency, check_dns=check)


@router.put("/domain", response_model=WorkspaceDomainOut)
def set_workspace_domain(
    payload: ClientDomainSet,
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user),
):
    agency = user.agency
    domain = payload.domain.strip().lower()
    if domain in (workspace_domain.primary_host(), workspace_domain.branded_host(agency)):
        raise HTTPException(status_code=400, detail="That address is already served by the platform")
    taken = db.scalar(select(Agency).where(Agency.workspace_domain == domain, Agency.id != agency.id))
    if taken or db.scalar(select(Client).where(Client.portal_domain == domain)):
        raise HTTPException(status_code=409, detail="That domain is already in use")
    if agency.workspace_domain != domain or not agency.workspace_domain_token:
        agency.workspace_domain_token = new_domain_token()
        agency.workspace_domain_verified = False
    agency.workspace_domain = domain
    db.commit()
    db.refresh(agency)
    return workspace_domain.describe(agency)


@router.post("/domain/verify", response_model=WorkspaceDomainOut)
def verify_workspace_domain(db: Session = Depends(get_db), user: User = Depends(get_current_user)):
    agency = user.agency
    if not agency.workspace_domain:
        raise HTTPException(status_code=400, detail="Add a domain before verifying it")
    if not dns_service.txt_contains(agency.workspace_domain, agency.workspace_domain_token):
        raise HTTPException(status_code=400, detail="The verification TXT record was not found yet. DNS can take a while to propagate.")
    agency.workspace_domain_verified = True
    db.commit()
    db.refresh(agency)
    return workspace_domain.describe(agency, check_dns=True)


@router.delete("/domain", response_model=WorkspaceDomainOut)
def delete_workspace_domain(db: Session = Depends(get_db), user: User = Depends(get_current_user)):
    agency = user.agency
    agency.workspace_domain = None
    agency.workspace_domain_verified = False
    agency.workspace_domain_token = ""
    db.commit()
    db.refresh(agency)
    return workspace_domain.describe(agency)
