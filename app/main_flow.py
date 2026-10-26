"""主线六步：给人看的那一条路，只在这里定义一次。

界面上的步骤名用业务说法 —— 创建企业 → 导入历史资料 → 导入当月资料 →
AI 处理 → 人工确认 → 凭证生成与复核 —— 不是内部阶段名。

**为什么必须只有一处定义**：实测分叉过一次。`ontology/service.py` 把同一组
id 叫「资料分析／待确认与校验」，`autonomous_workflow.py` 叫「自主分析／
独立审查」，同一个 `analysis` 在两条路径上显示成两个名字。两条路径各自算
状态是对的（它们的处理方式确实不同），但步骤的身份、顺序和"算不算主线"
不能各写一份。

**第 4 步吸收两个内部阶段**。月度自主处理内部是「自主分析」和「独立审查」
两步，都由机器完成，对使用的人是同一件事：AI 在处理。两步的细节进 summary，
不占主线的格子 —— 否则进度条会在一个人类无事可做的步骤上停着。

**第 5 步只放真正要人做的事**。自主处理里人工确认发生在 findings 循环
（`needs_user`），不是内部的「独立审查」阶段；传统管线里是「待确认与校验」。

**第 6 步保留「复核」两个字**。系统里的凭证是待复核候选，复核通过也不等于
已入账，叫「生成凭证」会越界 —— 这个边界是故意的，不要为了名字短而去掉。

**「交付归档」不在主线内**（`main_line=False`）。它在当前实现里永远是
WAITING，算进百分比会让人以为本月还差一步没做完。
"""

MAIN_LINE = (
    ('scope', '创建企业'),
    ('history', '导入历史资料'),
    ('source', '导入当月资料'),
    ('analysis', 'AI 处理'),
    ('confirmation', '人工确认'),
    ('voucher', '凭证生成与复核'),
)
ASIDE = (('delivery', '交付归档'),)
NAMES = dict(MAIN_LINE + ASIDE)
MAIN_LINE_IDS = tuple(stage_id for stage_id, _ in MAIN_LINE)
LAST_MAIN_LINE_ID = MAIN_LINE_IDS[-1]


def build(stages):
    """`{id: {status, summary, ...}}` → 完整的 progress 投影。

    主线六步必须都给齐；主线之外的步骤给了就带上，没给就不出现。
    """
    missing = [stage_id for stage_id in MAIN_LINE_IDS if stage_id not in stages]
    if missing:
        raise KeyError('主线步骤缺少状态：' + '、'.join(missing))
    items = [{'id': stage_id, 'name': name, 'main_line': True, **stages[stage_id]}
             for stage_id, name in MAIN_LINE]
    items += [{'id': stage_id, 'name': name, 'main_line': False, **stages[stage_id]}
              for stage_id, name in ASIDE if stage_id in stages]
    return summarize(items)


def summarize(stages):
    """按主线重算计数、百分比和当前步骤；主线之外的步骤不参与。

    没有标 `main_line` 的按主线算，这样只改了某一步状态的投影（例如
    `_progress_with_digestion`）可以直接把结果交回来重算。

    `can_wait` 的步骤不捕获当前指针。只有一处用它：历史账表正在被系统处理、
    或只差期初核实的时候 —— 那种状态下 prerequisite 自己的说明就是"处理期间
    可继续整理本期资料"，把指针停在第 2 步会让人不知道该去传当月资料。
    要人动手的历史问题不是 `can_wait`，它该捕获指针。
    没有别的候选时仍然指它，否则指针会落到一个已完成的步骤上。
    """
    main = [stage for stage in stages if stage.get('main_line', True)]
    completed = sum(stage['status'] == 'COMPLETED' for stage in main)
    open_stages = [stage for stage in main if stage['status'] != 'COMPLETED']
    current = next((stage['id'] for stage in open_stages if not stage.get('can_wait')),
                   next((stage['id'] for stage in open_stages), LAST_MAIN_LINE_ID))
    return {'stages': stages, 'completed_count': completed, 'total_count': len(main),
            'overall_percent': int(completed / len(main) * 100) if main else 0,
            'current_stage': current}
