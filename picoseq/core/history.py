"""アンドゥ / リドゥ — スナップショット方式の履歴。

スナップショットは直列化済み文字列。履歴自体も不変オブジェクト。
"""

from dataclasses import dataclass

HISTORY_LIMIT = 100


@dataclass(frozen=True)
class History:
    past: tuple = ()
    future: tuple = ()
    limit: int = HISTORY_LIMIT


def record(history: History, snapshot: str) -> History:
    """変更前のスナップショットを積む。リドゥ側は捨てる。"""
    past = history.past + (snapshot,)
    if len(past) > history.limit:
        past = past[-history.limit:]
    return History(past=past, future=(), limit=history.limit)


def can_undo(history: History) -> bool:
    return len(history.past) > 0


def can_redo(history: History) -> bool:
    return len(history.future) > 0


def undo(history: History, current: str):
    """(新しい履歴, 戻るスナップショット) を返す。戻れなければ None。"""
    if not history.past:
        return None
    snapshot = history.past[-1]
    return History(
        past=history.past[:-1],
        future=(current,) + history.future,
        limit=history.limit,
    ), snapshot


def redo(history: History, current: str):
    """(新しい履歴, 進むスナップショット) を返す。進めなければ None。"""
    if not history.future:
        return None
    snapshot = history.future[0]
    return History(
        past=history.past + (current,),
        future=history.future[1:],
        limit=history.limit,
    ), snapshot
