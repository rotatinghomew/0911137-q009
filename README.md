# 园区用量剖面台

用于查阅园区用量剖面的业务记录、当前摘要与保存的分析版本。现有功能包括业务范围筛选、历史时点查阅、原始资料展开、不可变分析结果回看，以及持续用量转折识别、改造前后基线比较与分析师边界决策。统计口径见 `docs/data-contract.md`，HTTP 结构见 `docs/http-api.md`。

## 转折分析与基线比较

曲线页面在日用量曲线之外提供：

- 累计表底只在同一表内作差、换表分段；识别在「气温 + 停工」调整后的残差上做带多重检验校正的持续偏移扫描，节假日与气温波动不会被当成改造。
- 候选分主要候选与弱观察，分析师可确认、驳回或在登记表单中手工调整边界；决策与证据快照独立固定，资料补抄回改只重算估计值，不会移动已确认边界。
- 节能量只用边界前可比资料拟合基线，并给出 95% 置信区间；未经历过的温度或生产组合列为支撑域外、排除在汇总之外并提示不能可靠估计。

## 运行

需要 Python >=3.11,<3.12，不依赖特定补丁版本。应用运行只使用标准库，浏览器 JavaScript 无构建步骤。以下命令在项目根目录执行：

```sh
python3 -m usage_regimes
```

浏览器打开本机 8080 端口即可操作。资料默认来自 `fixtures/data.json`；分析结果默认保存在 `.state/analyses.sqlite3`。可用 `--data` 指定同口径资料，`--state` 指定状态文件，`--port` 调整监听端口。

## 测试

```sh
python3 -m unittest discover -s tests -v
```

测试涵盖领域口径、真实 HTTP 往返、错误筛选、跨进程存储及不可变保存。页面直接消费与测试相同的 API，不使用预录结果。

浏览器验证工具与产品运行依赖分开锁定；准备一次后可重复执行筛选、保存、刷新回看和资料查阅：

```sh
python3 -m pip install -r requirements-test.txt
python3 -m playwright install --with-deps chromium
python3 tests/browser_smoke.py
```

前两条是首次测试环境安装，完成后无需重复执行。基础容器只运行产品和标准库测试；浏览器测试在安装了 `requirements-test.txt` 与 Chromium 的开发环境运行。

也可使用无第三方 JavaScript 依赖的 npm 工作区入口：`npm ci --ignore-scripts` 后，`npm start -- --host 127.0.0.1 --port 8080` 启动同一个 Python HTTP 服务，`npm run test:browser` 执行上述浏览器回归。npm 仅负责命令编排，不是产品运行依赖；不要把 `web/` 单独作为静态站点运行，页面需要同源 API。

## 容器

```sh
docker build -t usage-regimes:local .
docker run --rm -p 127.0.0.1:8080:8080 usage-regimes:local
```

基础镜像以内容摘要固定，Python 打包依赖固定在 `requirements-build.txt`。容器构建完成后可断网运行；若要保留容器外分析版本，可将宿主目录挂载到 `/app/.state`。

## 快速业务核对

```sh
python3 -m usage_regimes --demo
```

此入口启动真实本地 HTTP 服务，计算当前摘要，保存后重新读取再退出。输出依赖当前资料，不预先指定统计结论。初次阅读可先在页面调整时点或业务范围，再保存和回看分析；测试和该核对入口可在九十秒内完成，不包含镜像构建时间。
