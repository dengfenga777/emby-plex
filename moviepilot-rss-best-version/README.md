# RSS 优选下载插件

这是一个按 `MoviePilot-Plugins` 目录规范整理好的 V2 插件示例，目标是解决这个问题：

- 同一次 RSS 刷新里，同一部剧同一集可能同时出现 `4K` 和 `1080p`
- 默认逐条处理时，两个版本都有机会被下发到下载器
- 这个插件会先用 MoviePilot 识别媒体信息，再按 `TMDB + 季 + 集` 分组
- 每组只保留优先级最高的一个资源，默认顺序是 `2160p > 1080p > 720p > 其他`

当前版本是 `2.0.0`，重点不是继续堆规则，而是把流程收敛成四步：

- 收集 RSS 候选
- 识别媒体并归一化季集
- 只为同一集保留一个最优版本
- 下载成功后再回写历史

## 目录

- 插件代码：`plugins.v2/rssbestversion/__init__.py`
- 市场配置片段：`package.v2.snippet.json`

## 安装方式

1. 把 [plugins.v2/rssbestversion/__init__.py](/Users/cc/Documents/Playground/moviepilot-rss-best-version/plugins.v2/rssbestversion/__init__.py) 复制到你的 MoviePilot 插件仓库：
   `plugins.v2/rssbestversion/__init__.py`
2. 把 [package.v2.snippet.json](/Users/cc/Documents/Playground/moviepilot-rss-best-version/package.v2.snippet.json) 里的 `RssBestVersion` 条目合并进你的 `package.v2.json`
3. 提交到你自己的插件仓库，或者在本地开发仓库直接加载

## 当前行为

- 直接读取 RSS 条目
- 调用 MoviePilot 自身识别能力获取 `TMDB / 季 / 集`
- 对同一剧集按集号分组
- 同组多个资源时优先选择更高分辨率
- 同分辨率下支持站点优先级比较
- 同分辨率下，如果开启 `prefer_hevc`，优先 `HEVC/H.265`
- 可直接过滤整季/完结包
- 可直接过滤没有识别出集号的电视剧资源
- 下载成功后按“剧集键”记历史，后续不会再因为 1080p/4K 多版本重复下发
- 如果后续周期刷到同一集，但这次资源体积比历史里已推送版本更大，也会再次推送下载

## 适合你的场景

- PT 站 RSS 里同一集经常同时出 `4K` 和 `1080p`
- 你希望 `4K` 有就下 `4K`
- 没有 `4K` 的时候才下 `1080p`
- 不希望两个版本都进入下载器

## 一个重要说明

这个版本现在是“默认防重复，但允许更大体积版本升级重推”。也就是说：

- 如果第一次刷到的是 `1080p`
- 后面刷到一个体积更大的 `4K`
- 插件会把这个 `4K` 再次推送到下载器
- 但它只负责再次下发下载，不会自动删除旧版本，也不会自动做媒体库替换
