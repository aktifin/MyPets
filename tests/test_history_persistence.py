"""聊天记录与日常互动履历持久化与 UI 对话框联调单元测试模块。

验证 LocalStateStore 中 chat_history 与 interaction_records 的写入、倒序/顺序查询、
数量上限控制与一键清空能力，并验证 PetChatDialog 与 PetCarePanel 的图形回显与持久化捕获逻辑。
"""

from __future__ import annotations

from PySide6.QtWidgets import QApplication

from onepic_desktop_pet.local_store import LocalStateStore
from onepic_desktop_pet.pet_care_panel import PetCarePanel
from onepic_desktop_pet.pet_chat_dialog import PetChatDialog


def get_qapp() -> QApplication:
    app = QApplication.instance()
    if app is None:
        app = QApplication([])
    return app


def test_local_store_chat_history_crud(tmp_path):
    """测试 LocalStateStore 中聊天记录的增删改查与清空能力。"""
    db_file = tmp_path / "test_chat.sqlite3"
    store = LocalStateStore(db_file)

    try:
        pet_id = "test_pet_001"
        # 1. 写入用户消息与宠物回复
        m1 = store.save_chat_message(
            pet_id=pet_id,
            sender="user",
            sender_name="主人",
            content="你好呀小宠物！",
        )
        m2 = store.save_chat_message(
            pet_id=pet_id,
            sender="pet",
            sender_name="小美",
            content="主人好！很高兴见到你~",
            emotion="happy",
        )

        assert m1 and m2

        # 2. 查询列表
        history = store.list_chat_history(pet_id)
        assert len(history) == 2
        assert history[0]["content"] == "你好呀小宠物！"
        assert history[0]["sender_name"] == "主人"
        assert history[1]["content"] == "主人好！很高兴见到你~"
        assert history[1]["emotion"] == "happy"

        # 3. 清空列表
        store.clear_chat_history(pet_id)
        assert len(store.list_chat_history(pet_id)) == 0

    finally:
        store.close()


def test_local_store_interaction_records_crud(tmp_path):
    """测试 LocalStateStore 中日常互动履历的增删改查与清空能力。"""
    db_file = tmp_path / "test_inter.sqlite3"
    store = LocalStateStore(db_file)

    try:
        pet_id = "test_pet_002"
        # 1. 保存投喂与摸摸动作
        r1 = store.save_interaction_record(
            pet_id=pet_id,
            action_type="feed",
            action_name="投喂",
            detail="饱食度 +15, 经验 +5",
        )
        r2 = store.save_interaction_record(
            pet_id=pet_id,
            action_type="pet",
            action_name="摸摸",
            detail="心情 +10, 羁绊 +1",
        )

        assert r1 and r2

        # 2. 查询倒序记录
        records = store.list_interaction_records(pet_id)
        assert len(records) == 2
        # r2 是最新加入的，按 created_at 降序排在第 0 位
        assert records[0]["action_name"] == "摸摸"
        assert records[1]["action_name"] == "投喂"
        assert "饱食度 +15" in records[1]["detail"]

        # 3. 清空
        store.clear_interaction_records(pet_id)
        assert len(store.list_interaction_records(pet_id)) == 0

    finally:
        store.close()


def test_pet_chat_dialog_persistence(tmp_path):
    """测试 PetChatDialog 的历史记录恢复、实时消息存库与一键清空。"""
    _app = get_qapp()
    db_file = tmp_path / "test_dialog.sqlite3"
    store = LocalStateStore(db_file)

    try:
        pet_id = "chat_pet_99"
        dialog = PetChatDialog(
            pet_name="可爱的球球",
            store=store,
            pet_id=pet_id,
        )

        # 初始无历史记录，触发默认欢迎词写入
        history_init = store.list_chat_history(pet_id)
        assert len(history_init) == 1
        assert "主人主人！" in history_init[0]["content"]

        # 用户发送消息
        dialog.send_user_message("摸摸你")
        history_after = store.list_chat_history(pet_id)
        # 应该新增 1 条用户消息 + 1 条宠物回复
        assert len(history_after) == 3
        assert history_after[1]["content"] == "摸摸你"
        assert history_after[1]["sender"] == "user"

        # 关闭旧窗口，新建一个对话框加载历史
        dialog.close()
        dialog2 = PetChatDialog(
            pet_name="可爱的球球",
            store=store,
            pet_id=pet_id,
        )
        assert dialog2.msg_list.count() == 3

        # 清空历史
        dialog2.clear_chat_history()
        assert dialog2.msg_list.count() == 0
        assert len(store.list_chat_history(pet_id)) == 0

        dialog2.close()

    finally:
        store.close()


def test_pet_care_panel_interaction_record(tmp_path):
    """测试 PetCarePanel 在照料请求成功后写入互动日志。"""
    _app = get_qapp()
    db_file = tmp_path / "test_care.sqlite3"
    store = LocalStateStore(db_file)

    try:
        pet_id = "care_pet_88"
        panel = PetCarePanel(store=store, pet_id=pet_id)

        # 模拟玩家点击投喂
        panel._on_action_clicked("feed", "投喂")
        # 服务端返回成功
        panel.show_result("投喂成功！饱食度+20", error=False)

        records = store.list_interaction_records(pet_id)
        assert len(records) == 1
        assert records[0]["action_type"] == "feed"
        assert records[0]["action_name"] == "投喂"
        assert "饱食度+20" in records[0]["detail"]

        panel.close()

    finally:
        store.close()
