"""事项标题不该把原始数据摊在列表上。

交接说明 §7 第二件：右侧事项列表出现过
「提取字段：识别结果不稳定（<一串银行账号>、<另一串>…」 ——
既不简洁，也把银行账号露在了列表上。

标题取自 issue 的 `reason`，而 `reason` 是事项身份（去重按它、`dismissed`
也按它索引），不能改；能改的是显示出来的标题。
"""
import pytest

from app.materials import short_title
from app.task_descriptors import VERIFY_FIELD_LABELS


def test_the_account_number_never_reaches_the_list():
    """交接说明举的就是这一条。

    这里用的是编出来的账号。真账号不该再往仓库里写一份 —— 这条测试
    防的就是这件事，测试自己更不能犯。
    """
    title = short_title(
        'counterparty_account：识别结果不稳定（6222000000000000001、6222000000000000002），须人工核对')

    assert title == '对方账号：识别结果不稳定'
    assert '6222000' not in title


@pytest.mark.parametrize('reason,expected', [
    ('transaction_date：多次识别结果不一致（2026-08-01、2026-08-11），须比对原件确认',
     '交易日期：多次识别结果不一致'),
    ('balance：识别结果不稳定（12,345.67、12,845.67），须人工核对', '账户余额：识别结果不稳定'),
    ('summary：识别结果不稳定（收款、付款），须人工核对', '摘要：识别结果不稳定'),
])
def test_every_scanned_statement_dispute_loses_its_raw_values(reason, expected):
    assert short_title(reason) == expected


def test_a_cell_location_is_dropped_too():
    """括号里不只有账号 —— 表格类问题塞的是单元格定位，同样让标题变长变乱。"""
    assert short_title('unmapped_C：工资条表头与首块不同，请核对列含义（工资!C5）') == \
        '未识别列 C：工资条表头与首块不同，请核对列含义'


def test_an_english_field_name_becomes_the_one_chinese_name_we_already_use():
    """用核对卡那套 VERIFY_FIELD_LABELS，不另造一套词汇。"""
    assert short_title('period：工资期间标题冲突，须核对具体来源') == \
        f"{VERIFY_FIELD_LABELS['period']}：工资期间标题冲突，须核对具体来源"


def test_a_reason_that_is_already_a_sentence_is_left_alone():
    """不是「字段：说明」形状的，原样不动 —— 别把人话改坏了。"""
    for reason in ('个人报销往来无效：缺少报销人', '成果契约或来源结构错误', '票款待匹配无效：金额不符'):
        assert short_title(reason) == reason


def test_an_unknown_field_keeps_its_text_rather_than_guessing():
    """没收录的字段不硬翻，只把原始值去掉。"""
    assert short_title('mystery_field：识别结果不稳定（甲、乙），须人工核对') == \
        'mystery_field：识别结果不稳定'


def test_half_width_parentheses_are_cut_as_well():
    assert '12345' not in short_title('balance：识别结果不稳定(12345、12845)，须人工核对')


def test_the_generic_rule_is_worse_here_which_is_why_task_keeps_a_special_case():
    """「确认流水所属银行」说得清这件事要干嘛，通用规则给不出来。

    `MaterialReview.view` 的 `task()` 里对 `bank_account_ref：` 保留了特判，
    这条测试记着为什么不能把它删掉换成通用规则。
    """
    assert short_title('bank_account_ref：本方账户待人工核对') == '本方账户：本方账户待人工核对'
