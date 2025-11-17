from typing import Optional

from pydantic import BaseModel, Field


class UserAuth(BaseModel):
    username: str = Field(..., min_length=3, max_length=64)
    password: str = Field(..., min_length=6, max_length=64)


class UserBase(BaseModel):
    id: int
    username: str

    class Config:
        from_attributes = True


class CollectionCreate(BaseModel):
    title: str = Field(..., min_length=1, max_length=100)


class CollectionBase(BaseModel):
    id: int
    title: str
    user_id: int

    class Config:
        from_attributes = True


class ItemCreate(BaseModel):
    title: str = Field(..., min_length=1, max_length=100)
    link: Optional[str] = None
    notes: Optional[str] = None


class ItemBase(BaseModel):
    id: int
    title: str
    link: Optional[str] = None
    notes: Optional[str] = None
    collection_id: int

    class Config:
        from_attributes = True
