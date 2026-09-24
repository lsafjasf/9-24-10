# snapshotlib — 确定性快照测试框架（纯 Python 标准库）

## 快速开始

```python
from snapshotlib import SnapshotStore

store = SnapshotStore("__snapshots__")
store.assert_snapshot("user_profile", {"name": "ada", "roles": ["admin"]})
# 首次运行: 写入 __snapshots__/user_profile.snap.json (status="created")
# 之后运行: 比对, 不一致抛 SnapshotMismatchError (带路径级结构化差异)
store.assert_snapshot("user_profile", new_value, update=True)   # 显式更新, 留差异记录
# 或环境变量: SNAPSHOT_UPDATE=1 python3 -m unittest ...
```

## 运行命令

```bash
python3 -m unittest discover -s tests -v   # 全部自测 (42 个)
python3 -m unittest tests.test_concurrent -v  # 仅并发写测试
python3 demo_diff.py                        # 差异输出样例
```

## 序列化确定性如何保证

`snapshotlib/serialize.py` 把任意值归一化为**单行规范 JSON**，从根上消除无意义差异：

| 不确定性来源 | 保证机制 | 反例测试 (tests/test_serialize.py) |
|---|---|---|
| 字典键顺序 | 键按规范形式排序后输出 | 两种插入顺序的 dict → 字节相同；朴素 `json.dumps` 则不同 |
| 浮点格式 | `repr()` 最短往返格式；`-0.0`→`0.0`；NaN/Inf 打显式标签 | `-0.0` 与 `0.0` 字节相同（朴素 json 不同）；`0.1` 不会变成 `0.1000...01` |
| 换行 | 数据内换行被 JSON 转义；文件以二进制写，平台 `os.linesep` 无法渗入 | 含 `\n`/`\r\n` 的字符串序列化后全文仅 1 个记录终止换行；`\n` 与 `\r\n` 仍是真实差异 |
| 集合遍历顺序 | set/frozenset 成员按规范 JSON 排序 | 不同 `PYTHONHASHSEED` 子进程输出逐字节相同；朴素 `list(set)` 顺序随种子变化（反例） |

元组/集合/bytes/非标量键用 `~tuple`/`~set`/`~bytes`/`~dict` 标签编码，与列表/字符串键可区分。

## 并发写安全

- **无半写**：先写同目录临时文件 + `fsync` + `os.replace` 原子替换。
- **无静默覆盖**：每个快照一把锁（进程内 `threading.Lock` + 跨进程 `fcntl.flock`），读-改-写全程持锁。
- **冲突显式报错**：多名并发首次写同一快照 → 恰好 1 个 `created`，其余收到
  `SnapshotMismatchError`/`SnapshotConcurrentModificationError`；更新前复核 digest，
  读后被改则拒绝覆盖（见 `tests/test_concurrent.py`）。

## 可区分的异常

| 异常 | 含义 |
|---|---|
| `SnapshotMissingError` | 快照不存在且未允许创建 |
| `SnapshotCorruptError` | 文件无法解析 / 头部字段缺失 |
| `SnapshotTamperedError` | 可解析但 digest 不符 → 被手工修改（Corrupt 子类，可单独捕获） |
| `SnapshotMismatchError` | 值不匹配，携带结构化差异，`.report()` 可打印 |
| `SnapshotConcurrentModificationError` | 读后被并发/手工改写，拒绝覆盖 |

## 差异输出

精确到路径（`$.user.roles[2]`、`$.tags{"testing"}`），长值截断但保留总长与
sha256 定位信息。样例（`python3 demo_diff.py`）：

```
snapshot mismatch: user_profile (/tmp/.../user_profile.snap.json)
5 difference(s):
  + $.extra
      new: true
  ~ $.bio
      old: "a very long biography a very long biography a very long biography a very long b... <truncated: 266 chars total, sha256:5b4fdb273d95>
      new: "a very long biography a very long biography a very long biography a very long b... <truncated: 266 chars total, sha256:65d201c9f9ca>
  - $.tags{"testing"}
      old: "testing"
  + $.user.roles[2]
      new: "ops"
  ~ $.user.score
      old: 0.30000000000000004
      new: 0.3
```

## 更新留痕

`update=True`（或 `SNAPSHOT_UPDATE=1`）时，除原子重写快照外，追加一条 JSONL 到
`<name>.updates.jsonl`：时间戳、旧/新 digest、结构化 diff、旧/新完整 payload。

## 文件布局

```
snapshotlib/
  serialize.py   # 确定性规范序列化
  diff.py        # 路径级结构化 diff + 截断预览
  store.py       # 锁、原子写、校验、更新日志
  errors.py      # 可区分异常层级
tests/
  test_serialize.py   # 确定性 + 反例测试
  test_diff.py        # 路径精度与截断
  test_store.py       # 状态机与异常区分
  test_concurrent.py  # 多进程/多线程并发写
demo_diff.py          # 差异输出样例
```
