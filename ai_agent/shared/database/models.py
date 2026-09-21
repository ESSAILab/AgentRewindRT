from sqlalchemy import Boolean, Column, DateTime, Float, ForeignKey, Index, Integer, JSON, String, Text, func

from .connection import Base


class AgentSession(Base):
    """智能体会话审计表。"""

    __tablename__ = "agent_sessions"

    run_id = Column(String(255), primary_key=True, comment="智能体会话运行ID")
    nono_session_id = Column(String(255), nullable=False, comment="nono rollback session ID")
    original_request = Column(Text, nullable=False, comment="用户原始请求")
    agent_command = Column(JSON, comment="智能体命令")
    workspace = Column(Text, nullable=False, comment="工作空间")
    diff_ref = Column(JSON, nullable=False, comment="diff对象存储引用")
    conversation = Column(JSON, comment="智能体对话信息")
    status = Column(String(50), nullable=False, default="received", comment="处理状态")
    decision = Column(String(50), nullable=True, comment="用户决策")
    rollback_status = Column(String(50), nullable=False, default="not_requested", comment="韧性恢复状态")
    raw_event = Column(JSON, nullable=False, comment="原始会话事件")
    created_at = Column(DateTime, default=func.now(), comment="创建时间")
    updated_at = Column(DateTime, default=func.now(), onupdate=func.now(), comment="更新时间")

    __table_args__ = (
        Index("idx_agent_sessions_status", "status"),
        Index("idx_agent_sessions_rollback_status", "rollback_status"),
        Index("idx_agent_sessions_created", "created_at"),
    )


class AgentAdjudication(Base):
    """智能体会话增量裁决表。"""

    __tablename__ = "agent_adjudications"

    id = Column(String(255), primary_key=True, comment="裁决ID")
    run_id = Column(String(255), ForeignKey("agent_sessions.run_id"), nullable=False)
    verdict = Column(String(50), nullable=False, comment="裁决结果")
    risk_level = Column(String(50), nullable=False, comment="风险等级")
    out_of_intent = Column(Boolean, nullable=True, comment="是否超出原始意图")
    confidence = Column(Float, nullable=True, comment="置信度")
    summary = Column(Text, nullable=False, comment="裁决摘要")
    findings = Column(JSON, nullable=False, comment="发现列表")
    recommended_action = Column(String(100), nullable=False, comment="推荐动作")
    rollback_recommended = Column(Boolean, default=False, comment="是否建议韧性恢复")
    raw_result = Column(JSON, nullable=False, comment="原始裁决结果")
    created_at = Column(DateTime, default=func.now(), comment="创建时间")

    __table_args__ = (
        Index("idx_agent_adjudications_run", "run_id"),
        Index("idx_agent_adjudications_verdict", "verdict"),
        Index("idx_agent_adjudications_risk", "risk_level"),
    )


class AgentRollback(Base):
    """智能体会话韧性恢复表。"""

    __tablename__ = "agent_rollbacks"

    id = Column(String(255), primary_key=True, comment="恢复请求ID")
    run_id = Column(String(255), ForeignKey("agent_sessions.run_id"), nullable=False)
    nono_session_id = Column(String(255), nullable=False, comment="nono rollback session ID")
    nono_state_home = Column(Text, nullable=False, default="", comment="nono XDG_STATE_HOME")
    snapshot = Column(Integer, nullable=False, default=0, comment="恢复快照")
    requested_by = Column(String(255), nullable=False, comment="请求人")
    status = Column(String(50), nullable=False, comment="恢复状态")
    command_results = Column(JSON, comment="命令执行结果")
    error_message = Column(Text, comment="错误信息")
    requested_at = Column(DateTime, default=func.now(), comment="请求时间")
    completed_at = Column(DateTime, comment="完成时间")

    __table_args__ = (
        Index("idx_agent_rollbacks_run", "run_id"),
        Index("idx_agent_rollbacks_status", "status"),
        Index("idx_agent_rollbacks_requested", "requested_at"),
    )
