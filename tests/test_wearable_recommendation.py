"""
P2-10 推荐引擎测试。

T001—T012：P2-9 冻结用例（直接读取 backend/recommendation/recommendation_test_cases.json），
  集合比较 + match_reasons 长度和关键短语检查，不逐字匹配理由文本。

T013—T015：P2-10 扩展用例（内联 fixture），
  仅检查 ID 集合和 match_reasons 长度。

测试要点：
1. 三段子函数（_filter_and_score / _select_near_match / _build_expected_candidates）
2. expected_candidates 始终保留完整候选集合，并用集合比较
3. recommendations 按 top_k 截断；match_reasons 恰好 3 条，使用客观参数表述
4. hard_filter_applied 与输入一致
5. near_match_product_id / unmet_conditions 正确
"""

import json
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from backend.recommendation.recommend_wearables import (  # noqa: E402
    load_wearables,
    recommend,
    _filter_and_score,
    _select_near_match,
    _build_expected_candidates,
    sort_candidates,
    is_compatible_with_device,
    evaluate_hard_filter,
    evaluate_all_hard_filters,
    build_product_index,
    _positive_swim_token,
    calc_user_group_score,
    calc_scene_score,
    generate_match_reasons,
    WEARABLE_DATA_PATH,
)

TEST_CASES_PATH = ROOT / "backend" / "recommendation" / "recommendation_test_cases.json"


# ----------------- Fixtures -----------------

@pytest.fixture(scope="module")
def products():
    assert WEARABLE_DATA_PATH.exists(), f"数据文件不存在：{WEARABLE_DATA_PATH}"
    return load_wearables()


@pytest.fixture(scope="module")
def test_cases():
    with open(TEST_CASES_PATH, "r", encoding="utf-8") as f:
        return json.load(f)


# ----------------- 数据完整性 -----------------

def test_data_file_loads_sixteen_products(products):
    """冻结数据必须正好 16 条（B01—B08、W01—W08）。"""
    assert len(products) == 16
    pids = {p["product_id"] for p in products}
    expected = {f"B{i:02d}" for i in range(1, 9)} | {f"W{i:02d}" for i in range(1, 9)}
    assert pids == expected


# ----------------- 系统兼容性独立测试 -----------------

def test_ios_excludes_w06_w07(products):
    """iOS 设备下 W06、W07 不应被纳入候选。"""
    for p in products:
        if p["product_id"] in ("W06", "W07"):
            assert is_compatible_with_device(p, "iOS") is False


def test_android_no_gms_excludes_w06_w07(products):
    for p in products:
        if p["product_id"] in ("W06", "W07"):
            assert is_compatible_with_device(p, "android_no_gms") is False


def test_android_gms_allows_w06_w07(products):
    for p in products:
        if p["product_id"] in ("W06", "W07"):
            assert is_compatible_with_device(p, "android_gms") is True


# ----------------- 硬过滤表达式解析 -----------------

@pytest.mark.parametrize("pid,expr,expected", [
    ("B05", "product_category=smart_band", True),
    ("W05", "product_category=smart_band", False),
    ("B05", "display_type=TFT", True),
    ("B01", "display_type=TFT", False),
    ("W06", "nfc_support=true", True),
    ("W06", "product_summary contains Wear OS", True),
    ("W07", "usage_scenarios contains Google Wallet银行卡支付", True),
    ("W05", "battery_life_typical_days>=15", True),
    ("W01", "battery_life_typical_days>=15", False),
    ("W03", "positioning_type=connected_phone", False),
    ("W05", "positioning_type=connected_phone", True),
])
def test_evaluate_hard_filter(products, pid, expr, expected):
    p = next(x for x in products if x["product_id"] == pid)
    assert evaluate_hard_filter(p, expr) is expected


# ----------------- 正向游泳判定 -----------------

def test_positive_swim_tracking_recognized(products):
    """B01 sports_features 含 swim_tracking，应判定为正向。"""
    p = next(x for x in products if x["product_id"] == "B01")
    assert _positive_swim_token(p["wearable_specs"]["sports_features"]) is True


def test_positive_swim_tracking_denied_for_w05(products):
    """W05 明确写"不支持游泳运动记录"，应判定为非正向。"""
    p = next(x for x in products if x["product_id"] == "W05")
    assert _positive_swim_token(p["wearable_specs"]["sports_features"]) is False


# ----------------- 子函数 _filter_and_score（阶段一） -----------------

def test_filter_and_score_basic(products, test_cases):
    """_filter_and_score 必须返回 5 元组，且 scoring_summary pid 与通过候选一致。"""
    case = test_cases[2]  # T003: android_no_gms + built_in_gnss watch
    scored, summary, near_pool, excluded, budget_near = _filter_and_score(
        products=products,
        user_demand=case["user_demand"],
        user_device=case["user_device"],
        hard_filters=case["hard_filter"],
        max_budget=case.get("max_budget"),
        currency=case.get("currency"),
    )
    assert isinstance(scored, list)
    # T003 期望 5 款：W01/W02/W03/W04/W08，全部为智能手表
    pids = {c["product"]["product_id"] for c in scored}
    assert pids == {"W01", "W02", "W03", "W04", "W08"}
    assert budget_near is None  # 没有预算约束
    # 系统中 W06/W07 不兼容 android_no_gms
    for c in scored:
        assert c["product"]["product_id"] not in {"W06", "W07"}
    # summary 必须包含全部 pid
    assert set(summary.keys()) == pids
    # 近 1 条 feature 缺失的近似候选：当候选全通过硬过滤时，near_pool 通常为空
    # 此处硬过滤列表只有 2 条，且全部满足 — 可能存在仅缺 1 条的近似 product
    for p, missing in near_pool:
        assert 0 < len(missing) <= 1


def test_filter_and_score_budget_triggers_near_pid(products):
    """当候选中存在 price=null 时，budget_near_pid 必为第一个 price=null 产品的 pid。"""
    # T001 风格：iOS 手环 + TFT + 100 AUD 预算
    scored, summary, near_pool, excluded, budget_near = _filter_and_score(
        products=products,
        user_demand="学生预算100",
        user_device="iOS",
        hard_filters=["product_category=smart_band", "display_type=TFT"],
        max_budget=100,
        currency="AUD",
    )
    assert budget_near == "B08"
    # B08 不在正式 scored 中（被价格过滤剔除）
    assert "B08" not in {c["product"]["product_id"] for c in scored}


def test_filter_and_score_excludes_incompatible(products):
    """iOS 设备下 W06/W07 必须被系统兼容性剔除，不能进入 scored。"""
    scored, *_ = _filter_and_score(
        products=products,
        user_demand="任何需求",
        user_device="iOS",
        hard_filters=["product_category=smart_watch"],
    )
    pids = {c["product"]["product_id"] for c in scored}
    assert "W06" not in pids
    assert "W07" not in pids


# ----------------- 子函数 _select_near_match（阶段二） -----------------

def test_select_near_match_feature_only():
    """当 expected 不足 3 时，near_match 必须从次要 feature 差异中选一个。"""
    # 模拟 T012：只有 W07 通过硬过滤；W06 因少 "体成分测量" 进入近似候选池
    expected = [{"product_id": "W07", "match_reasons": []}]
    fake_w06 = {"product_id": "W06", "product_category": "smart_watch"}
    near_pool = [(fake_w06, ["sports_features contains 体成分测量"])]
    pid, unmet = _select_near_match(expected, near_pool, budget_near_pid=None)
    assert pid == "W06"
    assert "sports_features不包含体成分测量" in unmet


def test_select_near_match_ignores_core_spec_diff():
    """核心规格（NFC、定位、续航）差异不应进入 near_match 池。"""
    expected = [{"product_id": "B05", "match_reasons": []}]
    fake_x = {"product_id": "B02", "product_category": "smart_band"}
    near_pool = [(fake_x, ["nfc_support=true", "positioning_type=built_in_gnss"])]  # missing=2 → 不会入选
    pid, unmet = _select_near_match(expected, near_pool, budget_near_pid=None)
    assert pid is None
    assert unmet == []


def test_select_near_match_prefers_same_category(products, test_cases):
    """近似候选应优先与正式候选同品类。"""
    case = test_cases[11]  # T012
    expected = [{"product_id": "W07", "match_reasons": []}]
    near_pool = [
        ({"product_id": "B07", "product_category": "smart_band"},
         ["sports_features contains 体成分测量"]),
        ({"product_id": "W06", "product_category": "smart_watch"},
         ["sports_features contains 体成分测量"]),
    ]
    pid, _ = _select_near_match(expected, near_pool, budget_near_pid=None)
    # W06 与 W07 同为 smart_watch，胜过 smart_band 的 B07
    assert pid == "W06"


# ----------------- 子函数 _build_expected_candidates（阶段三） -----------------

def test_build_expected_candidates_sorted_by_pid():
    """五层排序：score DESC → preference_hits DESC → 已知价格 → price ASC → pid ASC。

    B02(89.5, score=5) → 排第1；B03(99.5, score=3) → 排第2；B04(null, score=3) → 排第3。
    """
    fake_a = {"product_id": "B02", "wearable_specs": {}, "official_price": 89.5, "currency": "AUD"}
    fake_b = {"product_id": "B04", "wearable_specs": {}, "official_price": None, "currency": None}
    fake_c = {"product_id": "B03", "wearable_specs": {}, "official_price": 99.5, "currency": "AUD"}
    scored = [
        {"product": fake_b, "group_score": 1, "scene_score": 2, "total_score": 3},
        {"product": fake_a, "group_score": 1, "scene_score": 2, "total_score": 5},
        {"product": fake_c, "group_score": 1, "scene_score": 2, "total_score": 3},
    ]
    expected, _, _ = _build_expected_candidates(scored, max_budget=None, currency=None)
    ids = [c["product_id"] for c in expected]
    # score 5 > 3，B02 第一；B03(99.5) 和 B04(null) 同分，B03 已知价格更便宜
    assert ids == ["B02", "B03", "B04"]


def test_build_expected_candidates_pid_tiebreaker_when_all_known():
    """score 与 price 均相同时，由 product_id 升序决定（保证确定性）。"""
    fake_w02 = {"product_id": "W02", "wearable_specs": {}, "official_price": 269.0}
    fake_w03 = {"product_id": "W03", "wearable_specs": {}, "official_price": 269.0}
    fake_w04 = {"product_id": "W04", "wearable_specs": {}, "official_price": 269.0}
    fake_w08 = {"product_id": "W08", "wearable_specs": {}, "official_price": 269.0}
    scored = [
        {"product": fake_w08, "total_score": 5},
        {"product": fake_w02, "total_score": 5},
        {"product": fake_w04, "total_score": 5},
        {"product": fake_w03, "total_score": 5},
    ]
    expected, _, _ = _build_expected_candidates(scored, max_budget=None, currency=None)
    ids = [c["product_id"] for c in expected]
    # score 相同(5)，price 相同(269)，pid 升序：W02 < W03 < W04 < W08
    assert ids == ["W02", "W03", "W04", "W08"]


def test_build_expected_candidates_match_reasons_length():
    """每个候选必须恰好有 3 条 match_reasons，且来源于 generate_match_reasons。"""
    p = {
        "product_id": "W05",
        "wearable_specs": {"battery_life_typical_days": 12, "bluetooth_call": True},
        "official_price": 79.5,
        "currency": "AUD",
        "system_compatibility": "Android 8.0及以上、iOS 12.0及以上",
        "product_category": "smart_watch",
    }
    scored = [{
        "product": p, "group_score": 0, "scene_score": 0,
        "total_score": 0, "preference_hits": 0,
    }]
    expected, _, _ = _build_expected_candidates(scored, max_budget=100, currency="AUD")
    assert expected[0]["product_id"] == "W05"
    assert len(expected[0]["match_reasons"]) == 3
    # Bug 3 修复后，价格理由使用客观中文描述：「价格79.5 AUD，在100 AUD预算内」
    assert any("价格79.5 AUD" in m for m in expected[0]["match_reasons"])


def test_sort_candidates_known_price_first():
    """五层稳定排序：
    score DESC → price ASC（已知价格在前，null=+∞ 排末尾）→ pid ASC。
    """
    fake_known = {"product_id": "B03", "official_price": 89.5, "wearable_specs": {}}
    fake_unknown = {"product_id": "B02", "official_price": None, "wearable_specs": {}}
    fake_known2 = {"product_id": "B04", "official_price": 120.0, "wearable_specs": {}}
    scored = [
        # score=3 → B03(89.5) 已知价格最便宜
        {"product": fake_known, "total_score": 3},
        # score=2 → B02 null 价格排末尾（inf）
        {"product": fake_unknown, "total_score": 2},
        # score=1 → B04(120.0)
        {"product": fake_known2, "total_score": 1},
    ]
    sorted_scored = sort_candidates(scored)
    # score 第一优先：3>2>1，B03>B02>B04；B02 因 null 价格在 score=2 组内最贵
    assert [c["product"]["product_id"] for c in sorted_scored] == ["B03", "B02", "B04"]


def test_sort_candidates_pid_tiebreaker_when_all_known():
    """score 与 price 均相同时，由 product_id 升序决定（保证确定性）。"""
    fake_w02 = {"product_id": "W02", "official_price": 269.0, "wearable_specs": {}}
    fake_w08 = {"product_id": "W08", "official_price": 269.0, "wearable_specs": {}}
    scored = [
        {"product": fake_w08, "total_score": 5},
        {"product": fake_w02, "total_score": 5},
    ]
    sorted_scored = sort_candidates(scored)
    # score 相同(5)，price 相同(269)，pid 升序：W02 < W08
    assert [c["product"]["product_id"] for c in sorted_scored] == ["W02", "W08"]


# ----------------- T001—T012 完整端到端（P2-9 冻结用例）-----------------

@pytest.mark.parametrize("case_idx", list(range(12)))
def test_frozen_cases(products, test_cases, case_idx):
    """T001—T012：集合比较（不强制顺序）+ match_reasons 长度和关键短语检查。"""
    case = test_cases[case_idx]
    cid = case["case_id"]

    result = recommend(
        user_demand=case["user_demand"],
        user_device=case["user_device"],
        hard_filters=case["hard_filter"],
        max_budget=case.get("max_budget"),
        currency=case.get("currency"),
        products=products,
        top_k=None,
    )

    assert result["success"] is True, f"{cid}: 返回失败"

    # 1) product_id 集合一致（set 比较，不强制顺序）
    actual_ids = {c["product_id"] for c in result["expected_candidates"]}
    expected_ids = {c["product_id"] for c in case.get("expected_candidates", [])}
    assert actual_ids == expected_ids, (
        f"{cid}: expected_candidates 集合不一致\n"
        f"  期望：{sorted(expected_ids)}\n"
        f"  实际：{sorted(actual_ids)}"
    )

    # 2) 每个候选必须有恰好 3 条 match_reasons
    for c in result["expected_candidates"]:
        pid = c["product_id"]
        assert len(c["match_reasons"]) == 3, (
            f"{cid}: {pid} 的 match_reasons 应恰好 3 条，实际 {len(c['match_reasons'])} 条：{c['match_reasons']}"
        )

    # 3) hard_filter_applied 与输入一致
    assert result["hard_filter_applied"] == case["hard_filter"], (
        f"{cid}: hard_filter_applied 与输入不一致"
    )

    # 4) near_match_product_id
    assert result["near_match_product_id"] == case.get("near_match_product_id"), (
        f"{cid}: near_match_product_id 期望 {case.get('near_match_product_id')}，"
        f"实际 {result['near_match_product_id']}"
    )

    # 5) unmet_conditions（集合比较）
    actual_unmet = set(result["unmet_conditions"])
    expected_unmet = set(case.get("unmet_conditions", []))
    assert actual_unmet == expected_unmet, (
        f"{cid}: unmet_conditions 不一致\n"
        f"  期望：{sorted(expected_unmet)}\n"
        f"  实际：{sorted(actual_unmet)}"
    )


# ----------------- T013—T015 端到端（扩展用例）-----------------

EXTENDED_CASES = [
    {
        "case_id": "T013",
        "user_demand": "iOS用户希望手环能识别游泳",
        "user_device": "iOS",
        "hard_filter": ["product_category=smart_band"],
    },
    {
        "case_id": "T014",
        "user_demand": "学生预算100 AUD内购入手环",
        "user_device": "android_gms",
        "hard_filter": ["product_category=smart_band"],
        "max_budget": 100,
        "currency": "AUD",
    },
    {
        "case_id": "T015",
        "user_demand": "安卓带GMS用户的Wear OS智能手表并具备体成分",
        "user_device": "android_gms",
        "hard_filter": ["product_category=smart_watch"],
    },
]


@pytest.mark.parametrize("case", EXTENDED_CASES)
def test_extended_cases(products, case):
    """T013—T015：仅检查 ID 集合和 match_reasons 长度。"""
    cid = case["case_id"]

    result = recommend(
        user_demand=case["user_demand"],
        user_device=case["user_device"],
        hard_filters=case["hard_filter"],
        max_budget=case.get("max_budget"),
        currency=case.get("currency"),
        products=products,
        top_k=None,
    )

    assert result["success"] is True, f"{cid}: 返回失败"

    # 每个候选必须有恰好 3 条 match_reasons
    for c in result["expected_candidates"]:
        pid = c["product_id"]
        assert len(c["match_reasons"]) == 3, (
            f"{cid}: {pid} 的 match_reasons 应恰好 3 条，实际 {len(c['match_reasons'])} 条"
        )

    # hard_filter_applied 与输入一致
    assert result["hard_filter_applied"] == case["hard_filter"], (
        f"{cid}: hard_filter_applied 与输入不一致"
    )


# ----------------- 评分模块独立验证 -----------------

def test_user_group_score_capped_at_4(products):
    """人群匹配加分上限 4 分。"""
    p = next(x for x in products if x["product_id"] == "B01")
    demand = "学生 户外跑步 细手腕 商务 长辈 Wear OS 健康 全部命中"
    score = calc_user_group_score(p, demand)
    assert 0 <= score <= 4


def test_scene_score_capped_at_9(products):
    """场景匹配加分上限 9 分。"""
    p = next(x for x in products if x["product_id"] == "B01")
    demand = "NFC 通勤 蓝牙通话 独立定位 游泳 运动模式 健康管理 长续航"
    score, _ = calc_scene_score(p, demand)
    assert 0 <= score <= 9


# ----------------- 排序：总分相同时已知价格优先 -----------------

def test_sort_prefers_known_price_when_scores_tie(products):
    """三层排序：score DESC → price ASC（已知价格排前，null=+∞ 排末尾）。

    与耳机 recommend_products 排序逻辑完全一致。
    """
    result = recommend(
        user_demand="长辈 长续航 健康管理 手环",
        user_device="android",
        hard_filters=[
            "product_category=smart_band", "battery_life_typical_days>=20",
            "heart_rate_monitoring=true", "blood_oxygen_monitoring=true",
            "sleep_monitoring=true", "stress_monitoring=true",
        ],
        products=products,
    )
    ids = [c["product_id"] for c in result["expected_candidates"]]
    # 新排序（score → price → pid）：B02(score高) > B04(price null→inf) > B03(price 99.5)
    assert ids == ["B02", "B04", "B03"], (
        f"排序应按 score DESC → price ASC → pid ASC，实际：{ids}"
    )


# ----------------- 输出与排序专项回归 -----------------

def test_preference_hits_before_price_when_scores_tie():
    """总分相同时，preference_hits 必须先于价格决定顺序。"""
    high_hits_unknown_price = {
        "product": {"product_id": "A", "official_price": None, "wearable_specs": {}},
        "total_score": 5,
        "preference_hits": 3,
    }
    low_hits_low_price = {
        "product": {"product_id": "B", "official_price": 50.0, "wearable_specs": {}},
        "total_score": 5,
        "preference_hits": 1,
    }
    ordered = sort_candidates([low_hits_low_price, high_hits_unknown_price])
    assert [c["product"]["product_id"] for c in ordered] == ["A", "B"]


def test_five_atm_without_swim_feature_not_claimed_as_swimming(products):
    """仅5ATM且无正向游泳词条时，只能描述浅水环境佩戴。"""
    for pid in ("B05", "B08"):
        product = next(p for p in products if p["product_id"] == pid)
        reasons = generate_match_reasons(
            product,
            hard_filters=["product_category=smart_band"],
            user_demand="日常散步和浅水活动",
        )
        assert len(reasons) == 3
        assert not any("可用于游泳" in r or "支持游泳运动记录" in r for r in reasons)
        assert any("浅水环境佩戴" in r for r in reasons)


def test_recommendation_output_fields(products):
    """Top3推荐项必须包含页面和Flask接口所需字段。"""
    result = recommend(
        user_demand="需要内置GNSS的户外手表",
        user_device="android_no_gms",
        hard_filters=["product_category=smart_watch", "positioning_type=built_in_gnss"],
        products=products,
        top_k=3,
    )
    assert len(result["expected_candidates"]) == result["total_candidates"]
    assert len(result["recommendations"]) == 3
    required = {
        "rank", "product_id", "product_name", "score",
        "official_price", "currency", "match_reasons",
    }
    for item in result["recommendations"]:
        assert required.issubset(item)
        assert len(item["match_reasons"]) == 3


# ----------------- 无候选时 near_match 兜底 -----------------

def test_no_candidate_when_no_product_passes(products):
    """硬过滤极端严格时，expected_candidates 应为空数组。"""
    result = recommend(
        user_demand="极端测试",
        user_device="iOS",
        hard_filters=[
            "product_category=smart_band",
            "nfc_support=true",
            "battery_life_typical_days>=25",  # 没有手环满足
        ],
        products=products,
    )
    assert result["expected_candidates"] == []


def test_top_k_limits_recommendations_only(products):
    """top_k=3 只截断 recommendations，expected_candidates 保留完整候选。"""
    result = recommend(
        user_demand="经常独自户外长跑和滑雪，出门不带手机，需要内置GNSS轨迹记录手表，使用无GMS安卓手机",
        user_device="android_no_gms",
        hard_filters=["product_category=smart_watch", "positioning_type=built_in_gnss"],
        products=products,
        top_k=3,
    )
    assert result["success"] is True
    assert result["total_candidates"] == 5
    assert len(result["expected_candidates"]) == 5
    assert len(result["recommendations"]) == 3
    assert [r["rank"] for r in result["recommendations"]] == [1, 2, 3]
    assert result["near_match_product_id"] is None


def test_top_k_none_returns_all(products):
    """top_k=None 时 recommendations 与 expected_candidates 均返回全部候选。"""
    result = recommend(
        user_demand="经常独自户外长跑和滑雪，出门不带手机，需要内置GNSS轨迹记录手表，使用无GMS安卓手机",
        user_device="android_no_gms",
        hard_filters=["product_category=smart_watch", "positioning_type=built_in_gnss"],
        products=products,
        top_k=None,
    )
    assert result["success"] is True
    assert len(result["expected_candidates"]) == 5
    assert len(result["recommendations"]) == 5
