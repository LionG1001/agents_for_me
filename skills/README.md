# User Skills

每个 User Skill 使用一个独立目录，目录名采用小写 kebab-case：

```text
skills/
└── example-skill/
    ├── SKILL.md
    ├── scripts/          # 可选：供 Skill 调用的脚本
    ├── references/       # 可选：按需读取的参考资料
    └── assets/           # 可选：模板或静态资源
```

约定：

- `SKILL.md` 是唯一必需文件，包含 YAML front matter 和完整使用说明。
- 一个 Skill 只负责一个清晰的工作流，避免把无关能力堆入同一目录。
- Token、密码、私钥及本机绝对路径不得提交到仓库。
- 脚本应提供明确输入、错误信息和安全默认值。
- 新增 Skill 后，在仓库根目录 `README.md` 的内容索引中添加入口。

本目录保存可分发的 Skill 源码。安装到本机时，将目标 Skill 目录复制到 `%USERPROFILE%\.codex\skills\`；系统内置 Skill 和插件缓存不纳入本仓库。
