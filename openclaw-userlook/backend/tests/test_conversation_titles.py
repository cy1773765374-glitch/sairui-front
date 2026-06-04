import unittest

from fastapi import HTTPException
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from app.core.database import Base
from app.models.agent import Agent, AgentRiskLevel
from app.models.conversation import Conversation
from app.models.message import Message
from app.models.message import MessageRole
from app.models.user import User, UserRole, UserStatus
from app.schemas.conversation import ConversationUpdate
from app.services.conversation_service import _maybe_auto_title_conversation, update_conversation_title


class ConversationTitleTest(unittest.TestCase):
    def setUp(self) -> None:
        engine = create_engine("sqlite:///:memory:", future=True)
        Base.metadata.create_all(engine)
        self.session_factory = sessionmaker(bind=engine, autoflush=False, autocommit=False)

    def test_first_user_message_auto_titles_default_conversation(self) -> None:
        with self.session_factory() as db:
            user, agent, conversation = self._seed(db)

            _maybe_auto_title_conversation(db, conversation, MessageRole.user, "你是谁")
            db.commit()
            db.refresh(conversation)

            self.assertEqual(conversation.title, "你是谁")
            self.assertFalse(conversation.is_title_manual)

            db.add(
                Message(
                    id=21,
                    conversation_id=conversation.id,
                    run_id=None,
                    role=MessageRole.user,
                    content="你是谁",
                    raw_payload=None,
                )
            )
            db.commit()
            _maybe_auto_title_conversation(db, conversation, MessageRole.user, "后续消息不应覆盖")
            db.commit()
            db.refresh(conversation)

            self.assertEqual(conversation.title, "你是谁")

    def test_manual_title_is_trimmed_limited_and_not_auto_overwritten(self) -> None:
        with self.session_factory() as db:
            user, agent, conversation = self._seed(db)

            updated = update_conversation_title(
                db,
                user,
                conversation.id,
                ConversationUpdate(title="  测试   刀版标题超过二十个字符不应完整保留额外内容  "),
            )
            db.refresh(conversation)

            self.assertEqual(updated.title, "测试 刀版标题超过二十个字符不应完整保留")
            self.assertTrue(conversation.is_title_manual)

            _maybe_auto_title_conversation(db, conversation, MessageRole.user, "你是谁")
            db.commit()
            db.refresh(conversation)

            self.assertEqual(conversation.title, "测试 刀版标题超过二十个字符不应完整保留")

    def test_non_owner_cannot_rename_conversation(self) -> None:
        with self.session_factory() as db:
            user, agent, conversation = self._seed(db)
            other_user = User(
                id=2,
                username="bob",
                password_hash="x",
                display_name="Bob",
                status=UserStatus.active,
                role=UserRole.user,
            )
            db.add(other_user)
            db.commit()

            with self.assertRaises(HTTPException):
                update_conversation_title(
                    db,
                    other_user,
                    conversation.id,
                    ConversationUpdate(title="不应成功"),
                )

    def _seed(self, db):
        user = User(
            id=1,
            username="alice",
            password_hash="x",
            display_name="Alice",
            status=UserStatus.active,
            role=UserRole.user,
        )
        agent = Agent(
            id=3,
            code="knife",
            name="刀版合成 Agent",
            openclaw_agent_id="knife-agent",
            risk_level=AgentRiskLevel.low,
        )
        conversation = Conversation(
            id=11,
            user_id=user.id,
            agent_id=agent.id,
            title=f"{agent.name} 对话",
            is_title_manual=False,
            session_key="web:1:knife:11",
        )
        db.add_all([user, agent, conversation])
        db.commit()
        return user, agent, conversation
