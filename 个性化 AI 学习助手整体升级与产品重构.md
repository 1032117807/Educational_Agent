# 个性化 AI 学习助手整体升级与产品重构

请基于当前已有的 **Learning Space / 个性化学习系统**继续开发。

本次不是重新创建一个新项目，也不要简单增加几个孤立页面，而是对当前系统进行一次**产品结构、学习闭环、AI 能力和 UI/UX 的整体升级**。

请首先完整阅读当前项目代码、数据库模型、API、页面、组件、Agent、RAG、Memory、Task、Goal、Practice 等现有实现，再进行修改。

必须尽量复用现有架构、数据库和功能。

不要为了重构而大规模推翻已经正常工作的模块。

---

# 一、产品重新定位

当前系统已经包含：

- Courses
- Tasks
- Goals & Knowledge
- Practice & Review
- Vocabulary
- Resources & RAG
- AI Center
- Learning Agent
- 学习计划
- AI 生题
- RAG
- 长期记忆
- Tool Calling / Skills
- 学习任务与提醒

目前的问题是：

这些能力更多是**独立存在的功能页面**，缺少真正的数据闭环。

希望把整个系统升级成：

> **AI Personalized Learning OS / Adaptive Learning Agent**

核心理念：

```text
Understand Me
    ↓
Plan For Me
    ↓
Teach Me
    ↓
Test Me
    ↓
Evaluate Me
    ↓
Adapt For Me
```

AI 不只是聊天机器人。

AI 应持续根据：

- 用户学习目标
- 考试日期
- 可用学习时间
- 当前知识掌握度
- 历史做题情况
- 错题
- 学习时间
- 学习完成率
- RAG 学习资料
- 长期记忆
- 最近学习行为

自动决定：

> 用户下一步最应该学习什么。

---

# 二、建立完整学习闭环

最终核心流程应为：

```text
用户创建学习目标
        ↓
AI 初始能力诊断
        ↓
建立知识点 / 知识结构
        ↓
生成学习路线
        ↓
生成阶段计划
        ↓
生成每日学习任务
        ↓
Today 今日学习
        ↓
学习资料 / AI Tutor / 做题
        ↓
收集学习结果
        ↓
更新知识掌握度
        ↓
分析错题和薄弱知识点
        ↓
安排间隔复习
        ↓
AI 动态修改后续计划
        ↓
提醒用户
        ↓
继续学习
```

请围绕这个闭环重新设计现有模块之间的关系。

不要让：

Courses、Tasks、Goals、Practice、RAG、AI Center

继续只是互相没有关系的 CRUD 页面。

---

# 三、第一优先级：新增 Today「今日学习中心」

这是本次最重要的新页面。

建议左侧导航第一项从：

```text
Overview
```

升级为：

```text
Today / 今日
```

Today 是用户每天打开应用首先看到的页面。

页面需要展示：

## 1. 今日概览

例如：

```text
早上好

距离 CET-6 考试还有 114 天

今日计划
60 min

已完成
25 min

完成率
42%
```

---

## 2. 今日任务

例如：

```text
今日学习计划

✓ 单词复习               15 min

○ 六级阅读训练           20 min

○ 昨日错题复习           10 min

○ 长难句专项训练         15 min

[继续学习]
```

每个任务必须可：

- 开始
- 完成
- 延期
- 调整
- 跳过
- 查看来源
- 查看所属课程
- 查看关联知识点

---

## 3. AI 今日建议

增加一个明显的 AI Insight Card：

```text
AI 学习建议

昨天你的阅读正确率为 62%。

主要错误集中在：

- 主旨题
- 同义替换

因此今天的阅读训练已经增加
3 道主旨题和 2 道同义替换题。
```

这个内容应该真正由学习数据生成，而不是写死。

---

## 4. 今日待复习

展示：

```text
今日待复习

12 个单词
8 道错题
5 个知识点
3 张知识卡片
```

按钮：

```text
[开始今日复习]
```

---

## 5. 薄弱知识点

展示：

```text
薄弱知识点

Taylor 展开      42%
定语从句          51%
同义替换          57%
```

允许：

```text
[开始专项训练]
```

---

# 四、重构 Courses：从课程卡片升级成 Learning Workspace

目前 Courses 不应该只是简单课程卡片。

点击某门课程后进入完整课程工作区。

例如：

```text
英语六级

目标：
CET-6 ≥ 500

考试：
2026-12

当前预测：
438

整体掌握度：
63%
```

课程内部建议包含：

```text
Overview
Plan
Knowledge
Materials
Practice
Mistakes
Notes
Analytics
```

Course 应成为所有学习数据的核心容器。

数据库关系应尽量形成：

```text
Course
│
├── Goal
├── Learning Plan
├── Knowledge Point
├── Resource
├── Question
├── Practice Session
├── Attempt
├── Mistake
├── Review
├── Note
└── Analytics
```

---

# 五、升级 Knowledge：建立学习者模型

当前 Knowledge Point 功能较弱。

不要要求用户主要依靠手动：

```text
Add knowledge point
```

应该支持 AI 自动建立知识结构。

例如上传：

```text
高等数学教材.pdf
教学大纲.pdf
历年试卷.pdf
```

AI 可以提取：

```text
高等数学
│
├── 极限
│   ├── 数列极限
│   ├── 函数极限
│   ├── 无穷小
│   └── 等价无穷小
│
├── 导数
│   ├── 导数定义
│   ├── 求导法则
│   └── 高阶导数
│
└── 积分
```

知识点之间支持：

- parent / child
- prerequisite
- related

至少预留知识图谱关系设计。

---

# 六、Knowledge Mastery：知识掌握度

每个 Knowledge Point 应维护学习状态，例如：

```text
mastery_score
confidence
practice_count
correct_count
wrong_count
last_studied_at
next_review_at
difficulty_level
recent_accuracy
```

其中：

```text
mastery_score ∈ [0, 1]
```

或：

```text
0 ～ 100
```

前端例如显示：

```text
Taylor 展开

掌握度       43%
最近正确率   50%
练习次数     12
最近学习     昨天
下次复习     明天
```

掌握度不能只由用户手工设置。

应根据：

- 答题正确率
- 难度
- 最近表现
- 重复错误
- 学习次数
- 时间衰减
- 复习表现

自动更新。

第一版无需实现非常复杂的机器学习算法。

可以设计一个清晰、可解释、可扩展的规则模型。

---

# 七、AI Learning Planner：动态学习规划

目前学习计划不能只做到：

```text
生成一次计划
```

需要升级成：

> Adaptive Learning Planner

输入包括：

```text
Goal
Deadline
Available Time
Knowledge Mastery
Recent Performance
Task Completion
Mistakes
Review Queue
Study History
User Preference
```

输出：

```text
Phase Plan
Weekly Plan
Daily Plan
```

例如：

```text
目标：
CET-6 500+

剩余：
114 天

每天：
60 min
```

自动规划：

```text
阶段一：基础能力
阶段二：专项训练
阶段三：真题强化
阶段四：冲刺
```

再进一步拆成：

```text
Week Plan
↓
Daily Tasks
```

---

# 八、计划必须可以动态调整

这是整个系统的核心能力之一。

例如：

原计划：

```text
阅读 30 min
听力 20 min
单词 20 min
```

用户最近实际每天只能完成：

```text
约 50 min
```

AI 应检测：

```text
计划完成率持续偏低
```

并建议：

```text
每日计划：

70 min
↓
55 min
```

如果发现：

```text
阅读正确率
62% → 82%

听力
68% → 51%
```

下一周可以自动建议：

```text
阅读
25min → 15min

听力
20min → 30min
```

所有计划调整必须保留：

- 修改前
- 修改后
- 调整原因

方便用户理解 AI 为什么改变计划。

---

# 九、重新设计 Practice & Review

当前 Practice 页面比较空。

需要升级为系统最核心的交互页面之一。

首页显示：

```text
今日推荐练习

AI 根据你的学习情况推荐：

长难句
5 题

主旨阅读
3 题

昨日错题
4 题

预计：
22 min

[开始智能练习]
```

同时保留：

```text
Question Bank
```

供用户自己选择题目。

---

# 十、支持 Rich Interactive Practice

练习不要只是把题目显示成文本。

需要真正支持交互组件。

题型至少预留：

```text
single_choice
multiple_choice
true_false
fill_blank
short_answer
calculation
essay
reading
```

例如：

```text
Question 3 / 10

████████░░

According to the passage...

○ A
○ B
○ C
○ D

[提示]

[提交]
```

---

# 十一、答题后立即 AI 反馈

提交题目后显示：

```text
回答错误

你的答案：
B

正确答案：
D
```

然后显示：

```text
AI 解析

本题考察：
同义替换

核心依据：
...

原文：
...

为什么 B 错：
...

为什么 D 对：
...
```

并提供：

```text
[给我换一种解释]

[生成一道类似题]

[加入错题本]

[问 AI]
```

---

# 十二、AI Question Factory：AI 生题系统

将目前：

```text
Generate with AI
```

升级成完整生题能力。

用户可以选择：

```text
课程

知识点

题型

难度

题量
```

来源支持：

```text
AI 自主生成

根据课程资料生成

根据某个 PDF 生成

根据错题生成

根据历年题风格生成

联网搜索题目

混合生成
```

例如：

```text
知识点：
Taylor 展开

难度：
中等

题型：
计算题

题量：
10

来源：
教材 + AI

[生成]
```

---

# 十三、生题必须增加质量控制

不要直接：

```text
LLM
↓
Question Bank
```

应该设计成：

```text
Knowledge Point
      ↓
Retrieve Evidence
      ↓
Question Generator
      ↓
Answer Generator
      ↓
Question Reviewer
      ↓
Duplicate Checker
      ↓
Difficulty Estimator
      ↓
Question Bank
```

Reviewer 至少检查：

- 题目是否完整
- 是否存在歧义
- 是否超纲
- 正确答案是否可靠
- 解析是否和答案一致
- 是否与已有题目高度重复

如果当前已经有 Multi-Agent / Skill 系统，可以合理复用。

但不要为了 Multi-Agent 而强行 Multi-Agent。

简单任务应保持简单。

---

# 十四、增加 Mistake Book 错题系统

新增完整错题能力。

每次错误应该记录：

```text
Question

User Answer

Correct Answer

Knowledge Point

Error Type

AI Analysis

Attempt Count

Created At

Last Reviewed At

Next Review At
```

AI 自动分析错误类型，例如：

```text
Concept Error

Understanding Error

Calculation Error

Memory Error

Careless Error

Unknown
```

---

# 十五、错误模式分析

Analytics 中显示：

```text
最近 30 道错题

概念错误        12

理解错误         8

计算错误         4

粗心             3

其他             3
```

AI 进一步总结：

```text
你并不是整个“极限”模块不会。

目前主要问题集中在：

等价无穷小替换的适用条件。
```

并允许：

```text
[生成专项训练]
```

---

# 十六、Spaced Repetition 间隔复习

Practice & Review 应建立统一 Review Engine。

支持：

```text
Vocabulary

Knowledge Point

Mistakes

Questions

Flashcards
```

例如：

```text
今天学习
↓
1 天后
↓
3 天后
↓
7 天后
↓
14 天后
↓
30 天后
```

无需严格照搬某一个算法。

可以先实现一个易维护、可调参数的间隔重复算法。

未来再替换 SM-2 / FSRS 等。

---

# 十七、Resources & RAG 升级成 Personal Knowledge Base

当前页面：

```text
Upload Resource

Library

Evidence Search
```

功能方向保留，但需要增强。

上传资源后显示：

```text
深入理解 AI Agent.pdf

125 pages

482 chunks

31 concepts

84 formulas

53 questions

Indexed ✓
```

提供：

```text
[阅读]

[AI 总结]

[生成笔记]

[提取知识点]

[生成练习]

[加入课程]

[搜索内容]
```

---

# 十八、资料处理流水线

设计为：

```text
Resource Upload
      ↓
Document Parsing
      ↓
Chunking
      ↓
Embedding
      ↓
RAG Index
      ↓
Concept Extraction
      ↓
Course Mapping
      ↓
Knowledge Point
```

如果现有项目已经实现其中部分能力，请复用。

不要重复实现已有基础设施。

---

# 十九、AI Center 改造成 Learning Copilot

保留现有 AI Center。

但是 AI 不应该只存在于 AI Center。

需要让 AI 能力出现在系统各处。

例如：

Course：

```text
AI 分析本课程
```

Knowledge：

```text
为什么我的掌握度这么低？
```

Practice：

```text
给我提示

换一种方式解释

再来一道类似题
```

Mistakes：

```text
分析我的错误模式
```

Resources：

```text
总结资料

生成题目

生成知识点
```

Plan：

```text
重新规划
```

Today：

```text
为什么今天安排这些内容？
```

AI Center 继续作为：

> 全局 Learning Agent 对话入口。

---

# 二十、AI Agent 必须理解当前学习上下文

用户在 AI Center 中问：

```text
我今天应该学什么？
```

Agent 不应该只靠 Prompt 猜。

应该能够读取：

```text
Current Goal

Current Course

Today's Tasks

Knowledge Mastery

Recent Mistakes

Recent Practice

Review Queue

Available Time

Learning History
```

再回答。

例如：

```text
你今天还有 55 分钟可学习。

根据最近 7 天的数据：

阅读正确率已经提升到 78%，
但听力仍只有 54%。

因此今天建议：

听力训练 25 min

昨日错题 15 min

单词复习 15 min
```

---

# 二十一、AI Tool / Skill 架构

请检查当前 Agent 的 Tool Calling / Skill 机制。

建议整理成清晰能力：

```text
Learning Agent
│
├── Planning Skill
│
├── Practice Skill
│
├── Question Generation Skill
│
├── Resource Search Skill
│
├── RAG Skill
│
├── Review Skill
│
├── Knowledge Analysis Skill
│
├── Reminder Skill
│
└── Web Search Skill
```

使用：

```text
Progressive Skill Disclosure
```

不要把所有 Skill 的完整 Prompt 一次性塞进 Context。

优先：

```text
Skill Metadata
↓
Skill Selection
↓
Load Skill Detail
↓
Tool Calling
```

---

# 二十二、Reminder 提醒系统升级

现有 reminder 功能继续保留。

增加：

```text
Fixed Reminder

Deadline Reminder

Review Reminder

Learning Plan Reminder

Incomplete Task Reminder
```

例如：

```text
19:00

你今天还有：

阅读训练 20 min

错题复习 10 min
```

或者：

```text
今天有 8 道错题进入复习周期。
```

未来可扩展：

```text
连续 3 天未学习

↓

AI 建议降低学习计划强度
```

---

# 二十三、Analytics 学习分析

新增：

```text
Learning Analytics
```

至少包括：

```text
学习时间

任务完成率

练习正确率

知识掌握度

薄弱知识点

错题数量

复习完成率

连续学习天数
```

支持趋势展示：

```text
Last 7 Days

Last 30 Days

All Time
```

例如：

```text
阅读正确率

Week 1    58%

Week 2    65%

Week 3    74%
```

---

# 二十四、AI Weekly Report

自动生成每周学习报告。

例如：

```text
本周学习时间
5h 32min

计划完成率
82%

完成练习
124 题

正确率
73%

掌握度提升最大：

函数极限
52% → 71%

仍需重点加强：

Taylor 展开
43%

AI 建议：

下周减少基础题，
增加 Taylor 展开专项训练。
```

---

# 二十五、重新设计导航

当前导航较碎：

```text
Overview

Courses

Tasks

Goals & knowledge

Practice & review

Vocabulary

Resources & RAG

AI Center

Team
```

建议重构成：

```text
Today

Courses

Learning Plan

Practice

Library

Analytics

AI Assistant
```

如果 Team 当前不是核心功能，可以放到底部或 Secondary Navigation。

不要删除已有功能。

将它们重新归类即可。

例如：

```text
Tasks
+
Goals

↓

Learning Plan
```

```text
Vocabulary

↓

Practice / Review
```

```text
Knowledge

↓

Course → Knowledge
```

```text
Resources & RAG

↓

Library
```

---

# 二十六、整体 UI 重构

当前 UI 存在大量横向空白。

在桌面宽屏下内容区域明显过窄。

请优化整体布局。

建议：

```text
Sidebar

+

Main Content max-width:
1200～1400px
```

Dashboard 可以采用：

```text
┌──────────────┬──────────────┬──────────────┐
│ 今日学习时间 │ 计划完成率    │ 当前连续天数 │
└──────────────┴──────────────┴──────────────┘

┌─────────────────────────────┬──────────────┐
│ Today Plan                  │ Due Review   │
│                             │              │
└─────────────────────────────┴──────────────┘

┌─────────────────────────────┬──────────────┐
│ Learning Progress           │ Weak Points  │
└─────────────────────────────┴──────────────┘
```

---

# 二十七、统一视觉语言

目前部分页面存在：

```text
Courses

Courses
```

这种重复标题。

请删除无意义重复层级。

同时解决：

- 中英文混杂
- 卡片留白过多
- 页面信息密度过低
- 按钮层级不明显
- 页面缺少状态反馈
- 不同页面布局不统一

UI 应偏：

> Modern AI Productivity / Learning Dashboard

而不是传统后台管理系统。

要求：

- 简洁
- 高信息密度但不拥挤
- 大量使用 Card
- 清晰 Typography
- 明确 Primary / Secondary Action
- 统一 Border Radius
- 统一 Spacing
- 统一 Button Style
- 统一 Empty State
- 统一 Loading
- 统一 Error State

---

# 二十八、删除开发感较强的信息

目前页面顶部类似：

```text
8a0e2bcc • owner

zhe
```

如果属于内部 workspace / debug 信息：

请重新设计显示方式。

不要让开发内部 ID 成为普通用户主要 UI。

例如可放入：

```text
Workspace Settings
```

或者直接隐藏。

---

# 二十九、Empty State 必须重新设计

例如不要只有：

```text
No knowledge points yet.
```

改成：

```text
还没有知识点

上传教材、课程大纲或让 AI 自动分析，
即可建立本课程的知识结构。

[AI 生成知识点]

[手动添加]
```

Practice：

```text
还没有练习内容

AI 可以根据：

课程资料
+
薄弱知识点
+
历史错题

自动生成适合你的练习。

[生成第一组练习]
```

---

# 三十、不要让 AI 功能表现成普通按钮堆积

AI 操作需要体现：

- 输入
- AI 正在处理
- Tool / Skill 状态
- 成功结果
- 来源
- 可确认操作

例如生成学习计划：

```text
Analyzing your learning profile...

✓ Goal

✓ Knowledge mastery

✓ Recent mistakes

✓ Available time

Generating plan...
```

最终：

```text
AI 已生成新的学习计划

[查看计划]

[应用]

[重新生成]
```

---

# 三十一、数据模型设计要求

请根据现有数据库检查并补齐必要实体。

建议至少具备概念：

```text
User

Course

Goal

LearningPlan

PlanPhase

Task

KnowledgePoint

KnowledgeRelation

KnowledgeMastery

Resource

ResourceChunk

Question

QuestionKnowledgePoint

PracticeSession

QuestionAttempt

Mistake

ReviewItem

LearningEvent

Reminder

Conversation

Memory
```

不要求机械照搬这些名字。

优先兼容当前已有模型。

如果已有功能可以通过增加字段或关系实现，就不要重新创建重复表。

---

# 三十二、Learning Event

建议增加统一学习行为日志。

例如：

```text
study_started

study_completed

question_answered

question_wrong

resource_read

knowledge_reviewed

task_completed

plan_adjusted
```

未来 Analytics 和 AI Planner 应基于真实行为数据运行。

---

# 三十三、Agent 的长期记忆

已有 Memory 系统继续保留。

但需要区分：

```text
User Preference Memory

Learning State

Conversation Memory

Knowledge Mastery

Learning Event
```

不要把所有东西全部塞进向量长期记忆。

例如：

```text
“用户喜欢晚上学习”
```

适合 Memory。

而：

```text
Taylor 掌握度 = 43%
```

应该存在结构化数据库。

---

# 三十四、RAG 与 Memory 分工

保持：

```text
RAG
→ 学习资料知识

Memory
→ 用户长期偏好与重要个人上下文

Database
→ 当前真实学习状态

Conversation
→ 当前对话上下文
```

Agent 回答时根据需要组合这些信息。

---

# 三十五、Web Search 搜题能力

AI 生题系统支持联网搜题。

流程建议：

```text
User Request
     ↓
Search Query Generation
     ↓
Web Search
     ↓
Candidate Questions
     ↓
Content Extraction
     ↓
Quality Filtering
     ↓
Duplicate Detection
     ↓
Knowledge Mapping
     ↓
Question Bank
```

必须保存来源。

对于联网获取的题目：

显示：

```text
Source
```

避免无法追踪来源。

---

# 三十六、AI 生题与联网搜题必须区分

数据库建议保存：

```text
source_type

ai_generated

resource_generated

web_collected

manual
```

方便：

- 溯源
- 分析
- 质量控制
- 后续筛选

---

# 三十七、Question Difficulty

题目支持：

```text
easy
medium
hard
```

未来可以根据用户答题表现动态估计难度。

推荐练习时：

如果知识掌握度较低：

```text
Easy → Medium
```

如果掌握度较高：

```text
Medium → Hard
```

形成简单 Adaptive Practice。

---

# 三十八、Practice Recommendation Engine

根据：

```text
Mastery

Recent Error

Review Due

Question Difficulty

User Goal

Exam Importance
```

生成：

```text
Recommended Questions
```

不要每次完全随机抽题。

---

# 三十九、AI Tutor Mode

在做题、资料阅读和课程页面都允许进入 AI Tutor。

例如用户说：

```text
我还是不理解洛必达法则
```

AI 不只是给答案。

可以：

```text
解释
↓

举例
↓

提问检查理解
↓

根据回答继续解释
```

支持：

```text
Explain

Hint

Socratic

Example

Quiz Me
```

---

# 四十、第一版开发优先级

不要一次性把所有高级能力全部写完。

请按照下面优先级开发。

## P0

必须优先完成：

```text
Today Dashboard

Course Workspace

Knowledge Mastery

智能 Practice

Mistake Book

Adaptive Learning Plan

现有模块数据打通
```

---

## P1

第二阶段：

```text
Spaced Repetition

Learning Analytics

AI Weekly Report

Resource → Knowledge Extraction

Question Factory

AI Tutor
```

---

## P2

后续预留：

```text
Full Knowledge Graph

Advanced Multi-Agent

Advanced Recommendation

Voice Tutor

Predictive Learning Model
```

---

# 四十一、工程要求

修改之前：

1. 阅读当前项目目录结构。
2. 阅读 README。
3. 阅读数据库模型。
4. 阅读 API。
5. 阅读前端页面与路由。
6. 阅读 Agent / Tool / Skill。
7. 阅读 RAG。
8. 阅读 Memory。
9. 阅读任务、目标、练习相关逻辑。

然后输出一个简短实施计划。

之后直接开始修改。

不要只给我建议。

不要只生成设计文档。

需要真正修改项目代码。

---

# 四十二、兼容性要求

必须：

```text
保留现有数据

保留现有 API 能力

保留现有 Agent

保留现有 RAG

保留现有 Memory

保留现有 Tool / Skill

保留当前已经可以工作的功能
```

允许：

- 重构 UI
- 重构导航
- 增加表字段
- 增加表关系
- 新增 API
- 新增组件
- 新增页面
- 新增 Migration
- 重构部分内部逻辑

但不要无理由推翻已有架构。

---

# 四十三、不要写死 Demo 数据

所有：

```text
Mastery

Today Plan

Weak Point

Learning Analytics

AI Insight

Practice Recommendation
```

必须尽可能来自真实数据库。

如果当前没有数据：

显示合理 Empty State。

不要为了页面看起来丰富而直接在代码中写死：

```text
Taylor 43%

Reading 62%

60 min
```

这些只能作为开发理解示例，不能成为最终实际数据。

---

# 四十四、状态必须完整

所有 AI 操作至少考虑：

```text
idle

loading

success

error

empty
```

长时间任务需要：

```text
processing

progress

completed

failed
```

避免用户点击：

```text
Generate with AI
```

之后完全不知道发生了什么。

---

# 四十五、最终目标

最终用户打开系统时，不应该感觉：

> 这里有很多学习工具。

而应该感觉：

> 这个 AI 知道我要学什么，
> 知道我现在会什么，
> 知道我哪里不会，
> 知道我今天应该做什么，
> 做完以后还会自动调整下一步。

核心产品闭环：

```text
Goal
 ↓
Diagnosis
 ↓
Plan
 ↓
Learn
 ↓
Practice
 ↓
Evaluate
 ↓
Mastery Update
 ↓
Review
 ↓
Replan
 ↓
Next Learning Session
```

系统最终定位：

> **Personalized Adaptive Learning Agent**

而不是：

> Chatbot + Todo + Question Bank + RAG。

---

# 四十六、本轮先执行的内容

本轮请优先真正实现：

1. 重构主导航。
2. 新建 / 重构 Today 页面。
3. 重构 Course Detail 为 Learning Workspace。
4. 建立 Knowledge Mastery 基础模型。
5. 重构 Practice 页面。
6. 建立 Question Attempt。
7. 建立 Mistake Book。
8. 将做题结果与 Knowledge Mastery 联动。
9. 将 Task / Goal / Learning Plan 打通。
10. Today 根据真实计划和 Review 数据生成今日内容。
11. 优化整体宽屏布局与信息密度。
12. 优化所有 Empty State。
13. 保证现有 RAG、AI Center、Memory、Skill 和历史数据继续可用。

高级 Knowledge Graph、复杂推荐算法和 Voice Tutor 暂时只保留接口与架构扩展空间，不要为了实现所有功能而使本轮修改失控。

---

# 四十七、完成后检查

修改完成后请：

1. 启动项目。
2. 检查数据库 Migration。
3. 检查所有页面是否可以访问。
4. 检查旧数据是否仍可读取。
5. 创建一个测试课程。
6. 创建学习目标。
7. 生成学习计划。
8. 创建或 AI 生成题目。
9. 完成一次练习。
10. 验证 Question Attempt 是否记录。
11. 验证错题是否进入 Mistake Book。
12. 验证 Knowledge Mastery 是否更新。
13. 验证 Today 是否反映最新状态。
14. 验证任务完成后 Today 是否同步变化。
15. 验证 RAG / AI Center / Memory 是否没有被破坏。
16. 修复运行过程中发现的错误。

如果项目已有测试框架，请补充相应测试。

不要只完成 UI。

本轮最重要的是：

> **把已有系统从“多个独立学习功能”，真正连接成一个可以持续感知、规划、练习、评估和调整的 AI 个性化学习闭环。**