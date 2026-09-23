from sqlalchemy import Column, Integer, String, Text, DateTime
from backend.database import Base
import datetime

class Setting(Base):
    __tablename__ = "settings"
    id = Column(Integer, primary_key=True, index=True)
    key = Column(String, unique=True, index=True)
    value = Column(Text)

class ExecutionLog(Base):
    __tablename__ = "execution_logs"
    
    id = Column(Integer, primary_key=True, index=True)
    task_id = Column(String, unique=True, index=True)
    
    # Store generic task inputs as JSON
    task_type = Column(String) # onpage, offpage, gmb, content, geo
    inputs_json = Column(Text)
    model_provider = Column(String) 
    
    status = Column(String) # pending, running, success, error
    
    result_json = Column(Text, nullable=True) 
    
    timestamp = Column(DateTime, default=datetime.datetime.utcnow)
