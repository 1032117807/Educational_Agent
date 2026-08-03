from collections.abc import Callable
from PySide6.QtCore import QObject, QRunnable, QThreadPool, Signal
from PySide6.QtWidgets import QLabel, QMessageBox, QComboBox, QHBoxLayout, QPushButton, QSpinBox, QTableWidget, QTableWidgetItem, QVBoxLayout, QWidget
from ai.chains import PlanGenerationService
from app.services.domain import JobService
from app.services.learning import LearningService

class PlanWorkerSignals(QObject):
    succeeded = Signal(int); failed = Signal(str); finished = Signal()

class PlanWorker(QRunnable):
    def __init__(self, factory, jobs, job_id, goal_id, daily_minutes):
        super().__init__(); self.factory=factory; self.jobs=jobs; self.job_id=job_id; self.goal_id=goal_id; self.daily_minutes=daily_minutes; self.signals=PlanWorkerSignals(); self.setAutoDelete(False)
    def run(self):
        try:
            self.jobs.update(self.job_id, "running", 10, "正在生成学习计划")
            draft_id=self.factory().generate(self.goal_id, daily_minutes=self.daily_minutes)
            self.jobs.update(self.job_id, "completed", 100, "学习计划生成完成")
            self.signals.succeeded.emit(draft_id)
        except Exception as exc:
            self.jobs.update(self.job_id, "failed", 100, "学习计划生成失败", str(exc)); self.signals.failed.emit(str(exc))
        finally: self.signals.finished.emit()

class AIPlanWidget(QWidget):
    tasks_changed=Signal(); jobs_changed=Signal()
    def __init__(self, *, learning: LearningService, jobs: JobService, factory: Callable[[], PlanGenerationService]):
        super().__init__(); self.learning=learning; self.jobs=jobs; self.factory=factory; self.current_draft_id=None
        root=QVBoxLayout(self); bar=QHBoxLayout(); self.goal=QComboBox(); self.minutes=QSpinBox(); self.minutes.setRange(5,480); self.minutes.setValue(120); self.minutes.setSuffix(" 分钟/天"); self.generate_button=QPushButton("AI 制定计划"); self.generate_button.clicked.connect(self.generate); bar.addWidget(QLabel("学习目标")); bar.addWidget(self.goal,1); bar.addWidget(self.minutes); bar.addWidget(self.generate_button)
        self.summary=QLabel(); self.table=QTableWidget(0,6); self.table.setHorizontalHeaderLabels(["日期","任务","时长","优先级","类型","依据"]); self.table.horizontalHeader().setStretchLastSection(True); actions=QHBoxLayout(); self.reject_button=QPushButton("拒绝草稿"); self.accept_button=QPushButton("确认并创建任务"); self.reject_button.setEnabled(False); self.accept_button.setEnabled(False); self.reject_button.clicked.connect(self.reject); self.accept_button.clicked.connect(self.accept); actions.addStretch(); actions.addWidget(self.reject_button); actions.addWidget(self.accept_button); root.addLayout(bar); root.addWidget(self.summary); root.addWidget(self.table); root.addLayout(actions); self.refresh_goals()
    def refresh_goals(self):
        self.goal.clear()
        for item in self.learning.list_goals():
            if item.status == "active": self.goal.addItem(f"{item.title} · {item.target_date}", item.id)
    def generate(self):
        if self.goal.currentData() is None: QMessageBox.warning(self,"缺少目标","请先创建学习目标。"); return
        job=self.jobs.create("plan_generation","生成 AI 学习计划"); self.generate_button.setEnabled(False); worker=PlanWorker(self.factory,self.jobs,job.id,self.goal.currentData(),self.minutes.value()); worker.signals.succeeded.connect(self.load); worker.signals.failed.connect(lambda m: QMessageBox.warning(self,"生成失败",m)); worker.signals.finished.connect(lambda: self.generate_button.setEnabled(True)); worker.signals.finished.connect(self.jobs_changed.emit); self.worker=worker; QThreadPool.globalInstance().start(worker)
    def load(self,draft_id):
        self.current_draft_id=draft_id; tasks=self.factory().list_tasks(draft_id); self.table.setRowCount(len(tasks));
        for row,item in enumerate(tasks):
            for col,value in enumerate((item.planned_date.isoformat(),item.title,f"{item.duration_minutes} 分钟",item.priority,item.task_type,item.reason)): self.table.setItem(row,col,QTableWidgetItem(str(value)))
        self.summary.setText(f"草稿包含 {len(tasks)} 项任务，请审核后确认。"); self.accept_button.setEnabled(True); self.reject_button.setEnabled(True)
    def accept(self):
        count=self.factory().confirm(self.current_draft_id); QMessageBox.information(self,"计划已采用",f"已创建 {count} 项学习任务。"); self.clear(); self.tasks_changed.emit()
    def reject(self): self.factory().reject(self.current_draft_id); self.clear()
    def clear(self): self.current_draft_id=None; self.table.setRowCount(0); self.summary.clear(); self.accept_button.setEnabled(False); self.reject_button.setEnabled(False)
