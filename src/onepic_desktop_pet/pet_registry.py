"""多宠物本地注册表与当前宠物选择服务。

该服务为后续账户同步和桌面宠物切换提供应用层入口。它不加载动画素材，也不负责
云端权限判断；云端接入后仍由服务端宠物状态覆盖本地缓存。
"""

from __future__ import annotations

from datetime import datetime

from .domain import AccountPetRelation, PetIdentity, PetProfile, PetRole
from .local_store import LocalStateStore

LOCAL_ACCOUNT_ID = "local-account"
LOCAL_DEFAULT_PET_ID = "local-default-pet"


class PetRegistry:
    """管理本地宠物列表和本设备当前宠物。"""

    def __init__(self, store: LocalStateStore) -> None:
        self.store = store

    def bootstrap_local_pet(self) -> PetProfile:
        """首次启动时建立兼容现有单机素材的默认宠物。"""

        active = self.active_pet()
        if active is not None:
            return active

        existing = self.store.list_pets()
        if existing:
            self.store.set_active_pet_id(existing[0].identity.pet_id)
            return existing[0]

        profile = PetProfile(
            identity=PetIdentity(
                pet_id=LOCAL_DEFAULT_PET_ID,
                name="我的宠物",
                template_id="local.default",
                template_version="1.0.0",
                identity_version="1.0.0",
                primary_owner_account_id=LOCAL_ACCOUNT_ID,
            ),
            updated_at=datetime.now().astimezone(),
        )
        self.register_pet(
            profile,
            AccountPetRelation(
                account_id=LOCAL_ACCOUNT_ID,
                pet_id=profile.identity.pet_id,
                role=PetRole.OWNER,
                affinity=50,
            ),
            make_active=True,
        )
        return profile

    def register_pet(
        self,
        profile: PetProfile,
        relation: AccountPetRelation | None = None,
        *,
        make_active: bool = False,
    ) -> None:
        """写入宠物及可选照料关系。"""

        if relation is not None and relation.pet_id != profile.identity.pet_id:
            raise ValueError("照料关系的 pet_id 必须与宠物资料一致")
        self.store.upsert_pet(profile)
        if relation is not None:
            self.store.upsert_relation(relation)
        if make_active or self.store.get_active_pet_id() is None:
            self.store.set_active_pet_id(profile.identity.pet_id)

    def list_pets(self) -> list[PetProfile]:
        """返回本设备已缓存的宠物资料。"""

        return self.store.list_pets()

    def active_pet(self) -> PetProfile | None:
        """返回当前宠物；失效选择会自动清理。"""

        pet_id = self.store.get_active_pet_id()
        if pet_id is None:
            return None
        profile = self.store.get_pet(pet_id)
        if profile is None:
            self.store.set_active_pet_id(None)
        return profile

    def switch_active_pet(self, pet_id: str) -> PetProfile:
        """切换本设备当前宠物，不修改其他设备。"""

        profile = self.store.get_pet(pet_id)
        if profile is None:
            raise KeyError(f"本地不存在宠物：{pet_id}")
        self.store.set_active_pet_id(pet_id)
        return profile
