from sqlalchemy import create_engine, Column, Integer, String, DateTime, Float
from sqlalchemy.ext.declarative import declarative_base
from sqlalchemy.orm import sessionmaker
import datetime
from datetime import datetime, timezone

SQLALCHEMY_DATABASE_URL = "sqlite:///./sql_app.db"

engine = create_engine(SQLALCHEMY_DATABASE_URL, connect_args={"check_same_thread": False})
SessionLocal = sessionmaker(autocommit=False, autoflush=False, bind=engine)
Base = declarative_base()

class Site(Base):
    __tablename__ = "sites"
    id = Column(Integer, primary_key= True, index= True)
    url = Column(String, unique = True , index= True)

class SiteStatus(Base):
    __tablename__ = "site_history"
    id = Column(Integer, primary_key = True , index = True)
    site_url = Column(String)
    status = Column(String)
    response_time = Column(Float)
    timestamp = Column (DateTime, default = lambda:datetime.now(timezone.utc))

Base.metadata.create_all(bind=engine)
