"""Keep every tool and parameter; remove the provider's repeated UI-only directive."""
from copy import deepcopy

LINK_PRESENTATION = '【链接】响应中 rows[i] / items[i] / 嵌套股票列表里的每个对象都含 code/name 字段。最终回答中列举具体股票时必须按 `[name(code)](https://stock.quicktiny.cn/quote/<code>)` 格式输出 markdown 链接（例：`[贵州茅台(600519)](https://stock.quicktiny.cn/quote/600519)`），让用户能点击查看行情；不要简化为「名称 + 代码」纯文本。'


def research_tool_schemas(schemas: list[dict]) -> list[dict]:
    result = deepcopy(schemas)
    for schema in result:
        body = schema.get('function', schema)
        description = body.get('description')
        if isinstance(description, str):
            body['description'] = description.replace(LINK_PRESENTATION, '返回的股票对象含code/name。')
    return result
