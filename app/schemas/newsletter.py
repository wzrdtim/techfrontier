from pydantic import BaseModel, ConfigDict, EmailStr


class NewsletterSubscribe(BaseModel):
    email: EmailStr


class SubscriberResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    email: EmailStr
