"""告警通道的域契约：一条消息长什么样、一个通道要会做什么。

这里**只有形状，没有传输**。域层不 import httpx / sqlite3 / smtplib
（`.importlinter` 的 `domain-no-web-framework` 契约会拦），
具体怎么发在 ``src.ops.infrastructure.notify_channels``。

分成两层的理由：注册表要能在不碰任何 HTTP 代码的前提下被测到——
「未配置的通道不发」「一个通道挂了不影响别的」这类判断是**策略**，
不该跟企微的 JSON body 长什么样绑在一起。
"""
from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass
from typing import Any, Literal, Protocol, runtime_checkable

__all__ = ["NotifyLevel", "NotifyMessage", "NotifyChannel"]

NotifyLevel = Literal["info", "warn", "critical"]


@dataclass(frozen=True, slots=True)
class NotifyMessage:
    """一条待推送的告警。

    ``frozen`` 是刻意的：同一条消息会被并行发给多个通道，任何一个通道在
    发送途中改了正文（截断、加前缀），别的通道就会收到被污染的版本。
    通道要改内容只能自己拷一份。
    """

    title: str
    body: str
    level: NotifyLevel = "info"
    link: str = ""
    tags: tuple[str, ...] = ()

    def as_text(self) -> str:
        """降级成纯文本：只认 text 的通道（企微/钉钉/飞书）共用这一份拼法。

        标题与正文之间换行；``link`` 单独起一行，免得被正文末尾的标点粘住。
        """
        parts = [self.title.strip(), self.body.strip()]
        text = "\n".join(part for part in parts if part)
        link = self.link.strip()
        if link:
            text = f"{text}\n{link}" if text else link
        return text

    def fingerprint(self) -> str:
        """限流用的消息指纹。

        只取 title/level/body，**不取 link 和 tags**：同一次任务重试生成的
        链接可能带不同的 run_id，把它算进指纹等于每次重试都是「新消息」，
        限流就白做了——而要防的正是任务重试风暴。
        """
        return "\x1f".join((self.title.strip(), self.level, self.body.strip()))


@runtime_checkable
class NotifyChannel(Protocol):
    """一个可插拔的推送通道。

    ``send`` 的契约是**永不抛异常**：失败返回 False 即可。一个通道挂掉不能
    带死调用它的任务，更不能带死同一批里的其他通道。
    """

    name: str
    label: str

    def is_configured(self, config: Mapping[str, Any]) -> bool:
        """配置是否足够发出一条消息（只看字段，不做网络探测）。"""
        ...

    def send(self, message: NotifyMessage, config: Mapping[str, Any]) -> bool:
        """发送；成功返回 True。失败只记日志并返回 False，不抛。"""
        ...
