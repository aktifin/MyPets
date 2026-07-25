"""主人与宠物自适应性格分析及独一无二互动生成引擎。

本模块根据平日聊天文本语义、交互频率与健康打卡行为，在本地非侵入式分析
【主人性格画像】（关怀型/工作狂/幽默/活力/严谨），并驱动【宠物 5 维演化性格】
（活泼/娇嗔/稳重/贴心/傲娇），从而生成独一无二的定制语气、气泡与桌面互动。
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Dict, List, Tuple


@dataclass
class MasterPersonalityProfile:
    """主人性格画像。"""

    primary_trait: str = "温暖关怀型"  # 温暖关怀型 / 专注工作狂型 / 幽默风趣型 / 元气活力型 / 严谨细致型
    caring_score: int = 50
    workaholic_score: int = 50
    witty_score: int = 50
    energetic_score: int = 50
    meticulous_score: int = 50
    total_chat_count: int = 0

    def update_trait(self) -> None:
        """更新最高权重主标签。"""
        scores = {
            "温暖关怀型": self.caring_score,
            "专注工作狂型": self.workaholic_score,
            "幽默风趣型": self.witty_score,
            "元气活力型": self.energetic_score,
            "严谨细致型": self.meticulous_score,
        }
        self.primary_trait = max(scores, key=scores.get)


@dataclass
class PetPersonalityEvolution:
    """宠物 5 维演化性格积分。"""

    lively: int = 50     # 活泼
    coquettish: int = 50 # 娇嗔
    steady: int = 50     # 稳重
    caring: int = 50     # 贴心
    tsundere: int = 50   # 傲娇

    def get_dominant_trait(self) -> str:
        """获取宠物主导性格倾向。"""
        traits = {
            "活泼型": self.lively,
            "娇嗔型": self.coquettish,
            "稳重型": self.steady,
            "贴心型": self.caring,
            "傲娇型": self.tsundere,
        }
        return max(traits, key=traits.get)


class PersonalityEngine:
    """自适应性格分析与独一无二互动生成引擎。"""

    def __init__(self) -> None:
        self.master_profile = MasterPersonalityProfile()
        self.pet_evolution = PetPersonalityEvolution()

    def analyze_chat_text(self, text: str) -> None:
        """分析聊天文本语义，更新主人画像与宠物演化倾向。"""
        self.master_profile.total_chat_count += 1
        t = text.lower()

        # 关怀词汇匹配
        if any(w in t for w in ["摸摸", "辛苦", "加油", "喝水", "关心", "身体", "爱"]):
            self.master_profile.caring_score += 3
            self.pet_evolution.caring += 2
            self.pet_evolution.coquettish += 1

        # 工作狂词汇匹配
        if any(w in t for w in ["工作", "忙", "加班", "开会", "代码", "项目", "提交"]):
            self.master_profile.workaholic_score += 3
            self.pet_evolution.tsundere += 2
            self.pet_evolution.steady += 1

        # 幽默词汇匹配
        if any(w in t for w in ["哈哈", "搞笑", "笨旦", "笨蛋", "逗", "笑死"]):
            self.master_profile.witty_score += 3
            self.pet_evolution.lively += 2
            self.pet_evolution.coquettish += 1

        # 活力词汇匹配
        if any(w in t for w in ["走动", "运动", "冲", "玩", "吃", "开心"]):
            self.master_profile.energetic_score += 3
            self.pet_evolution.lively += 2

        # 严谨词汇匹配
        if any(w in t for w in ["检查", "计划", "打卡", "准时", "提醒"]):
            self.master_profile.meticulous_score += 3
            self.pet_evolution.steady += 2

        self.master_profile.update_trait()

    def calculate_harmony_index(self) -> int:
        """计算主人与宠物的性格契合度指数 (0 - 100)。"""
        base = 60
        bonus = min(35, self.master_profile.total_chat_count * 2)
        return min(100, base + bonus)

    def generate_tailored_reply(self, text: str) -> Tuple[str, str]:
        """根据【主人标签 ✖ 宠物性格】生成独一无二的定制语气、对话与情绪。"""
        self.analyze_chat_text(text)
        master_tag = self.master_profile.primary_trait
        pet_tag = self.pet_evolution.get_dominant_trait()

        t = text.lower()

        # 针对不同组合生成专属互动话术
        if master_tag == "专注工作狂型":
            if pet_tag == "傲娇型":
                return "哼，虽然我知道你工作很拼，但要是累坏了可没人理你，快去喝水！", "angry"
            elif pet_tag == "贴心型":
                return "主人又在辛苦忙碌啦，小桌宠会一直静静陪着你，记得多休息哦~", "blush"
            else:
                return f"工作狂主人又在打字啦，打个哈欠提醒你动一动！", "happy"

        elif master_tag == "温暖关怀型":
            if pet_tag == "娇嗔型":
                return "呜呜主人最好了！好想一直在你怀里贴贴~ (๑•̀ㅂ•́)و", "blush"
            else:
                return f"收到主人的温暖关怀！我的心里也超级暖和呢~", "happy"

        elif master_tag == "幽默风趣型":
            return f"哈哈！主人说话总是这么有意思，小桌宠被你给逗笑了！(≧▽≦)", "happy"

        # 默认自适应通用专属口吻
        if "摸摸" in t:
            return f"[{pet_tag}] 蹭蹭{master_tag}主人的手~ 契合度上升！", "blush"
        elif "喝水" in t or "休息" in t:
            return f"[{pet_tag}] 收到指令！和{master_tag}主人一起喝水打卡~ 🍵", "happy"
        else:
            return f"[{pet_tag}] “{text}” —— 无论什么时候，我都会一直陪伴在主人身边！", "happy"
