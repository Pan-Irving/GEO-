# MySQL 体积优化说明

旧部署出现几十 GB MySQL 体积时，通常不是项目文件本身大，而是正文和 JSON 在多个表里重复保存，再叠加 binlog 和 InnoDB 删除后空间未释放。

## 新代码已减少后续放大

- `writing_content_items` 不再为 `article` 步骤重复保存完整正文。
- `writing_content_items.raw_json` 和 `writing_articles.raw_json` 改成轻量索引快照，不再重复塞完整 `markdown`。
- 已有的增量同步逻辑会跳过未变化的大字段，减少无意义 UPDATE 和 binlog。
- 发布库仍保留 `article_snapshots.markdown`，因为发布工作台预览、下载和员工发布需要正文。

## 旧库清理方式

先完整备份 `geo_writing` 和 `geo_publishing`，再在 MySQL 管理工具中按需执行：

```text
scripts/mysql-size-optimization.sql
```

建议顺序：

1. 先运行脚本里的表大小查询，确认大表是不是 `writing_steps`、`writing_content_items`、`writing_articles`、`article_snapshots` 或 binlog。
2. 在撰文库执行清理 `writing_content_items` / `writing_articles` 冗余字段的 UPDATE。
3. 低峰期执行脚本里注释的 `OPTIMIZE TABLE`，释放 InnoDB 表空间。
4. 检查 `SHOW BINARY LOGS`，确认备份和复制策略后再清理过期 binlog。

不要直接删除业务表。`writing_steps.output_json` 和 `publishing.article_snapshots.markdown` 仍是当前业务读取链路需要的数据。
