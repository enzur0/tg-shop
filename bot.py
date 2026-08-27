import asyncio
import logging
import json
import re
import shutil
from pathlib import Path
from datetime import datetime, timedelta
from typing import Optional, List, Dict
from enum import Enum

from aiogram import Bot, Dispatcher, Router, F
from aiogram.types import Message, CallbackQuery, InlineKeyboardMarkup, InlineKeyboardButton, MessageEntity, ErrorEvent
from aiogram.exceptions import TelegramBadRequest, TelegramUnauthorizedError
from aiogram.filters import Command
from aiogram.fsm.context import FSMContext
from aiogram.fsm.state import State, StatesGroup
from aiogram.fsm.storage.memory import MemoryStorage
from aiogram.client.default import DefaultBotProperties
from aiogram.enums import ParseMode

from sqlalchemy import Column, Integer, String, Float, Boolean, DateTime, ForeignKey, Text, select, update, delete, func, or_
from sqlalchemy.ext.asyncio import create_async_engine, async_sessionmaker, AsyncSession
from sqlalchemy.orm import declarative_base, relationship, selectinload
from sqlalchemy.sql import func as sql_func

import os
import sys
import ctypes
from dotenv import load_dotenv

# Configurare logging
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s - %(name)s - %(levelname)s - %(message)s",
)
logger = logging.getLogger(__name__)

_instance_mutex = None


def acquire_single_instance() -> bool:
    global _instance_mutex

    if os.name != "nt":
        return True

    kernel32 = ctypes.windll.kernel32
    _instance_mutex = kernel32.CreateMutexW(None, False, "NumeleMagazinuluiTauBotSingleInstance")
    if not _instance_mutex:
        return False
    return kernel32.GetLastError() != 183

# Încărcare variabile de mediu
load_dotenv()

# Configurare
BOT_TOKEN = os.getenv("BOT_TOKEN", "")


def load_admin_ids() -> List[int]:
    admin_ids = []
    for value in os.getenv("ADMIN_IDS", "").split(","):
        value = value.strip()
        if value.isdigit():
            admin_ids.append(int(value))
    return admin_ids

ADMIN_IDS = load_admin_ids()
DATABASE_URL = os.getenv("DATABASE_URL", "sqlite+aiosqlite:///./shop.db")
BACKUP_DIR = Path(os.getenv("BACKUP_DIR", "backups"))
STORE_NAME = os.getenv("STORE_NAME", "Numele Magazinului tau")

# Database setup
engine = create_async_engine(DATABASE_URL, echo=False)
async_session = async_sessionmaker(engine, class_=AsyncSession, expire_on_commit=False)
Base = declarative_base()

# ============ MODELE ============

class UserRole(str, Enum):
    CUSTOMER = "CUSTOMER"
    ADMIN = "ADMIN"

class OrderStatus(str, Enum):
    NEW = "NEW"
    CONFIRMED = "CONFIRMED"
    HANDED_TO_POST = "HANDED_TO_POST"
    SHIPPED = "SHIPPED"
    RECEIVED = "RECEIVED"
    CANCELLED = "CANCELLED"

class User(Base):
    __tablename__ = "users"
    
    id = Column(Integer, primary_key=True, index=True)
    telegram_id = Column(Integer, unique=True, index=True, nullable=False)
    username = Column(String, nullable=True)
    first_name = Column(String, nullable=True)
    last_name = Column(String, nullable=True)
    role = Column(String, default=UserRole.CUSTOMER.value)
    created_at = Column(DateTime(timezone=True), server_default=sql_func.now())
    updated_at = Column(DateTime(timezone=True), onupdate=sql_func.now())
    
    cart_items = relationship("CartItem", back_populates="user")
    orders = relationship("Order", back_populates="user")
    profile = relationship("CustomerProfile", back_populates="user", uselist=False)

class CustomerProfile(Base):
    __tablename__ = "customer_profiles"
    
    id = Column(Integer, primary_key=True, index=True)
    user_id = Column(Integer, ForeignKey("users.id"), unique=True, nullable=False)
    full_name = Column(String, nullable=True)
    postal_code = Column(String, nullable=True)
    phone = Column(String, nullable=True)
    district_village = Column(String, nullable=True)
    created_at = Column(DateTime(timezone=True), server_default=sql_func.now())
    updated_at = Column(DateTime(timezone=True), onupdate=sql_func.now())
    
    user = relationship("User", back_populates="profile")

class Category(Base):
    __tablename__ = "categories"
    
    id = Column(Integer, primary_key=True, index=True)
    name = Column(String, unique=True, nullable=False)
    created_at = Column(DateTime(timezone=True), server_default=sql_func.now())

class Product(Base):
    __tablename__ = "products"
    
    id = Column(Integer, primary_key=True, index=True)
    name = Column(String, nullable=False)
    description = Column(Text, nullable=True)
    price = Column(Float, nullable=False)
    old_price = Column(Float, nullable=True)
    category = Column(String, nullable=False)
    stock = Column(Integer, default=0)
    is_active = Column(Boolean, default=True)
    photo_file_id = Column(String, nullable=True)
    features = Column(Text, nullable=True)
    created_at = Column(DateTime(timezone=True), server_default=sql_func.now())
    updated_at = Column(DateTime(timezone=True), onupdate=sql_func.now())
    
    cart_items = relationship("CartItem", back_populates="product")

class CartItem(Base):
    __tablename__ = "cart_items"
    
    id = Column(Integer, primary_key=True, index=True)
    user_id = Column(Integer, ForeignKey("users.id"), nullable=False)
    product_id = Column(Integer, ForeignKey("products.id"), nullable=False)
    quantity = Column(Integer, default=1)
    created_at = Column(DateTime(timezone=True), server_default=sql_func.now())
    updated_at = Column(DateTime(timezone=True), onupdate=sql_func.now())
    
    user = relationship("User", back_populates="cart_items")
    product = relationship("Product", back_populates="cart_items")

class Order(Base):
    __tablename__ = "orders"
    
    id = Column(Integer, primary_key=True, index=True)
    order_number = Column(Integer, unique=True, nullable=False)
    user_id = Column(Integer, ForeignKey("users.id"), nullable=False)
    total = Column(Float, nullable=False)
    status = Column(String, default=OrderStatus.NEW.value)
    full_name = Column(String, nullable=False)
    postal_code = Column(String, nullable=False)
    phone = Column(String, nullable=False)
    district_village = Column(String, nullable=False)
    created_at = Column(DateTime(timezone=True), server_default=sql_func.now())
    updated_at = Column(DateTime(timezone=True), onupdate=sql_func.now())
    
    user = relationship("User", back_populates="orders")
    items = relationship("OrderItem", back_populates="order", cascade="all, delete-orphan")
    history = relationship("OrderHistory", back_populates="order", cascade="all, delete-orphan")

class OrderItem(Base):
    __tablename__ = "order_items"
    
    id = Column(Integer, primary_key=True, index=True)
    order_id = Column(Integer, ForeignKey("orders.id"), nullable=False)
    product_id = Column(Integer, ForeignKey("products.id"), nullable=False)
    product_name = Column(String, nullable=False)
    price = Column(Float, nullable=False)
    quantity = Column(Integer, nullable=False)
    subtotal = Column(Float, nullable=False)
    
    order = relationship("Order", back_populates="items")

class OrderHistory(Base):
    __tablename__ = "order_history"
    
    id = Column(Integer, primary_key=True, index=True)
    order_id = Column(Integer, ForeignKey("orders.id"), nullable=False)
    actor_id = Column(Integer, nullable=False)
    actor_type = Column(String, nullable=False)
    old_status = Column(String, nullable=False)
    new_status = Column(String, nullable=False)
    note = Column(Text, nullable=True)
    created_at = Column(DateTime(timezone=True), server_default=sql_func.now())
    
    order = relationship("Order", back_populates="history")

# ============ STATES ============

class OrderStates(StatesGroup):
    full_name = State()
    postal_code = State()
    phone = State()
    district_village = State()
    confirm = State()

class ProductStates(StatesGroup):
    waiting_for_name = State()
    waiting_for_description = State()
    waiting_for_price = State()
    waiting_for_old_price = State()
    waiting_for_category = State()
    waiting_for_stock = State()
    waiting_for_features = State()
    waiting_for_photo = State()
    waiting_for_product_id = State()
    waiting_for_new_price = State()
    waiting_for_new_stock = State()

class CategoryStates(StatesGroup):
    waiting_for_name = State()
    waiting_for_delete = State()

class OfferStates(StatesGroup):
    waiting_for_product_id = State()
    waiting_for_discount = State()

class ProfileStates(StatesGroup):
    waiting_for_name = State()
    waiting_for_postal_code = State()
    waiting_for_phone = State()
    waiting_for_district = State()

class SearchStates(StatesGroup):
    query = State()

class ResetStates(StatesGroup):
    first_confirmation = State()
    second_confirmation = State()

# ============ KEYBOARDS ============

def get_main_keyboard(is_admin: bool = False) -> InlineKeyboardMarkup:
    buttons = [
        [InlineKeyboardButton(text="🛍️ Catalog", callback_data="catalog")],
        [InlineKeyboardButton(text="🔥 Oferte", callback_data="offers")],
        [InlineKeyboardButton(text="🔎 Caută", callback_data="search")],
        [InlineKeyboardButton(text="🛒 Coșul meu", callback_data="cart")],
        [InlineKeyboardButton(text="📦 Comenzile mele", callback_data="my_orders")],
        [InlineKeyboardButton(text="👤 Profil", callback_data="profile")],
        [InlineKeyboardButton(text="ℹ️ Despre noi", callback_data="about")],
        [InlineKeyboardButton(text="💬 Contact", callback_data="contact")],
    ]
    
    if is_admin is True:
        buttons.append([InlineKeyboardButton(text="👨‍💼 Admin Panel", callback_data="admin_panel")])
    
    return InlineKeyboardMarkup(inline_keyboard=buttons)

def get_back_keyboard(callback_data: str = "back_to_main") -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="⬅️ Înapoi", callback_data=callback_data)]
    ])

def get_catalog_keyboard(categories: List[Category] = None) -> InlineKeyboardMarkup:
    if categories is None:
        categories = []
    
    buttons = []
    
    # Adăugăm categoriile din baza de date
    for i in range(0, len(categories), 2):
        row = []
        for category in categories[i:i+2]:
            row.append(InlineKeyboardButton(
                text=category.name, 
                callback_data=f"category_{category.name}"
            ))
        buttons.append(row)
    
    # Adăugăm butonul pentru toate produsele
    buttons.append([InlineKeyboardButton(text="📋 Toate produsele", callback_data="category_all")])
    buttons.append([InlineKeyboardButton(text="🔥 Oferte", callback_data="offers")])
    buttons.append([InlineKeyboardButton(text="⬅️ Înapoi", callback_data="back_to_main")])
    
    return InlineKeyboardMarkup(inline_keyboard=buttons)

def get_product_keyboard(product_id: int, has_stock: bool = True, category: str = None) -> InlineKeyboardMarkup:
    buttons = []
    
    if has_stock:
        buttons.append([InlineKeyboardButton(
            text="🛒 Adaugă în coș", 
            callback_data=f"add_to_cart_{product_id}"
        )])
    
    if category:
        buttons.append([InlineKeyboardButton(
            text="🔙 Înapoi la categorie", 
            callback_data=f"category_{category}"
        )])
    
    buttons.append([InlineKeyboardButton(text="🔙 Înapoi la catalog", callback_data="catalog")])
    
    return InlineKeyboardMarkup(inline_keyboard=buttons)

def get_cart_keyboard(has_items: bool = True) -> InlineKeyboardMarkup:
    buttons = []
    
    if has_items:
        buttons.append([InlineKeyboardButton(text="📦 Plasează comanda", callback_data="checkout")])
        buttons.append([InlineKeyboardButton(text="🗑️ Golește coșul", callback_data="clear_cart")])
    
    buttons.append([InlineKeyboardButton(text="⬅️ Înapoi", callback_data="back_to_main")])
    
    return InlineKeyboardMarkup(inline_keyboard=buttons)

def get_order_detail_keyboard(order: Order) -> InlineKeyboardMarkup:
    buttons = []
    
    if order.status == OrderStatus.SHIPPED.value:
        buttons.append([InlineKeyboardButton(
            text="✅ AM PRIMIT COLETUL", 
            callback_data=f"confirm_received_{order.id}"
        )])
    
    buttons.append([InlineKeyboardButton(text="⬅️ Înapoi", callback_data="my_orders")])
    
    return InlineKeyboardMarkup(inline_keyboard=buttons)

def get_admin_keyboard() -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="📦 Comenzi", callback_data="admin_orders")],
        [InlineKeyboardButton(text="⌚ Produse", callback_data="admin_products")],
        [InlineKeyboardButton(text="🏷️ Categorii", callback_data="admin_categories")],
        [InlineKeyboardButton(text="🔥 Oferte", callback_data="admin_offers")],
        [InlineKeyboardButton(text="📊 Statistici", callback_data="admin_statistics")],
        [InlineKeyboardButton(text="👥 Clienți", callback_data="admin_clients")],
        [InlineKeyboardButton(text="⬅️ Înapoi", callback_data="back_to_main")],
    ])

def get_admin_products_keyboard() -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="➕ Adaugă produs", callback_data="admin_add_product")],
        [InlineKeyboardButton(text="📋 Lista produse", callback_data="admin_list_products")],
        [InlineKeyboardButton(text="🗑️ Șterge produs", callback_data="admin_delete_product")],
        [InlineKeyboardButton(text="💰 Modifică preț", callback_data="admin_update_price")],
        [InlineKeyboardButton(text="📦 Modifică stoc", callback_data="admin_update_stock")],
        [InlineKeyboardButton(text="⬅️ Înapoi", callback_data="admin_panel")],
    ])

def get_product_category_keyboard(categories: List[Category]) -> InlineKeyboardMarkup:
    buttons = [
        [InlineKeyboardButton(
            text=category.name,
            callback_data=f"product_category_{category.id}"
        )]
        for category in categories
    ]
    buttons.append([
        InlineKeyboardButton(text="Anulează", callback_data="cancel_product_creation")
    ])
    return InlineKeyboardMarkup(inline_keyboard=buttons)

def get_admin_categories_keyboard() -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="➕ Adaugă categorie", callback_data="admin_add_category")],
        [InlineKeyboardButton(text="🗑️ Șterge categorie", callback_data="admin_delete_category")],
        [InlineKeyboardButton(text="📋 Lista categorii", callback_data="admin_list_categories")],
        [InlineKeyboardButton(text="⬅️ Înapoi", callback_data="admin_panel")],
    ])

def get_admin_offers_keyboard() -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="➕ Setează ofertă", callback_data="admin_set_offer")],
        [InlineKeyboardButton(text="❌ Anulează ofertă", callback_data="admin_remove_offer")],
        [InlineKeyboardButton(text="📋 Produse cu oferte", callback_data="admin_list_offers")],
        [InlineKeyboardButton(text="⬅️ Înapoi", callback_data="admin_panel")],
    ])

def get_admin_orders_keyboard() -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="🆕 Noi", callback_data="admin_orders_new")],
        [InlineKeyboardButton(text="🟡 Confirmate", callback_data="admin_orders_confirmed")],
        [InlineKeyboardButton(text="📮 La Poștă", callback_data="admin_orders_post")],
        [InlineKeyboardButton(text="🚚 Expediate", callback_data="admin_orders_shipped")],
        [InlineKeyboardButton(text="✅ Finalizate", callback_data="admin_orders_received")],
        [InlineKeyboardButton(text="❌ Anulate", callback_data="admin_orders_cancelled")],
        [InlineKeyboardButton(text="📋 Toate comenzile", callback_data="admin_all_orders")],
        [InlineKeyboardButton(text="⬅️ Înapoi", callback_data="admin_panel")],
    ])

# ============ SERVICES ============

class CategoryService:
    @staticmethod
    async def get_all_categories() -> List[Category]:
        async with async_session() as session:
            result = await session.execute(
                select(Category).order_by(Category.name)
            )
            return result.scalars().all()

    @staticmethod
    async def get_category(category_id: int) -> Optional[Category]:
        async with async_session() as session:
            result = await session.execute(
                select(Category).where(Category.id == category_id)
            )
            return result.scalar_one_or_none()
    
    @staticmethod
    async def add_category(name: str) -> Optional[Category]:
        async with async_session() as session:
            # Verificăm dacă există deja
            existing = await session.execute(
                select(Category).where(Category.name == name)
            )
            if existing.scalar_one_or_none():
                return None
            
            category = Category(name=name)
            session.add(category)
            await session.commit()
            await session.refresh(category)
            logger.info(f"Category created: {name}")
            return category
    
    @staticmethod
    async def delete_category(name: str) -> bool:
        async with async_session() as session:
            result = await session.execute(
                select(Category).where(Category.name == name)
            )
            category = result.scalar_one_or_none()
            
            if not category:
                return False
            
            await session.delete(category)
            await session.commit()
            logger.info(f"Category deleted: {name}")
            return True

class UserService:
    @staticmethod
    async def get_or_create_user(telegram_id: int, username: str = None, first_name: str = None, last_name: str = None) -> User:
        async with async_session() as session:
            result = await session.execute(
                select(User).where(User.telegram_id == telegram_id)
            )
            user = result.scalar_one_or_none()
            
            if not user:
                user = User(
                    telegram_id=telegram_id,
                    username=username,
                    first_name=first_name,
                    last_name=last_name,
                    role=UserRole.ADMIN.value if telegram_id in ADMIN_IDS else UserRole.CUSTOMER.value
                )
                session.add(user)
                await session.commit()
                await session.refresh(user)
                logger.info(f"New user created: {telegram_id}")
            
            return user
    
    @staticmethod
    async def get_customer_profile(telegram_id: int) -> Optional[CustomerProfile]:
        async with async_session() as session:
            result = await session.execute(
                select(CustomerProfile)
                .join(User)
                .where(User.telegram_id == telegram_id)
            )
            return result.scalar_one_or_none()
    
    @staticmethod
    async def save_customer_profile(telegram_id: int, data: dict) -> bool:
        async with async_session() as session:
            user_result = await session.execute(
                select(User).where(User.telegram_id == telegram_id)
            )
            user = user_result.scalar_one_or_none()
            
            if not user:
                return False
            
            profile_result = await session.execute(
                select(CustomerProfile).where(CustomerProfile.user_id == user.id)
            )
            profile = profile_result.scalar_one_or_none()
            
            if profile:
                for key, value in data.items():
                    setattr(profile, key, value)
            else:
                profile = CustomerProfile(user_id=user.id, **data)
                session.add(profile)
            
            await session.commit()
            logger.info(f"Profile saved for user: {telegram_id}")
            return True
    
    @staticmethod
    async def get_all_clients() -> List[User]:
        async with async_session() as session:
            result = await session.execute(
                select(User).where(User.role == UserRole.CUSTOMER.value)
            )
            return result.scalars().all()

class ProductService:
    @staticmethod
    async def get_active_products() -> List[Product]:
        async with async_session() as session:
            result = await session.execute(
                select(Product).where(Product.is_active == True)
            )
            return result.scalars().all()
    
    @staticmethod
    async def get_all_products() -> List[Product]:
        async with async_session() as session:
            result = await session.execute(
                select(Product).order_by(Product.created_at.desc())
            )
            return result.scalars().all()
    
    @staticmethod
    async def get_product(product_id: int) -> Optional[Product]:
        async with async_session() as session:
            result = await session.execute(
                select(Product).where(Product.id == product_id)
            )
            return result.scalar_one_or_none()
    
    @staticmethod
    async def get_products_by_category(category: str) -> List[Product]:
        async with async_session() as session:
            result = await session.execute(
                select(Product).where(
                    Product.category == category,
                    Product.is_active == True
                )
            )
            return result.scalars().all()
    
    @staticmethod
    async def get_products_with_discount() -> List[Product]:
        async with async_session() as session:
            result = await session.execute(
                select(Product).where(
                    Product.old_price.isnot(None),
                    Product.old_price > 0,
                    Product.is_active == True
                )
            )
            return result.scalars().all()
    
    @staticmethod
    async def search_products(query: str) -> List[Product]:
        async with async_session() as session:
            result = await session.execute(
                select(Product).where(
                    or_(
                        Product.name.ilike(f"%{query}%"),
                        Product.category.ilike(f"%{query}%"),
                        Product.description.ilike(f"%{query}%")
                    ),
                    Product.is_active == True
                )
            )
            return result.scalars().all()
    
    @staticmethod
    async def create_product(data: dict) -> Product:
        async with async_session() as session:
            product = Product(**data)
            session.add(product)
            await session.commit()
            await session.refresh(product)
            logger.info(f"Product created: {product.id} - {product.name}")
            return product
    
    @staticmethod
    async def update_product(product_id: int, data: dict) -> Optional[Product]:
        async with async_session() as session:
            await session.execute(
                update(Product)
                .where(Product.id == product_id)
                .values(**data)
            )
            await session.commit()
            
            result = await session.execute(
                select(Product).where(Product.id == product_id)
            )
            return result.scalar_one_or_none()
    
    @staticmethod
    async def delete_product(product_id: int) -> bool:
        async with async_session() as session:
            result = await session.execute(
                select(Product).where(Product.id == product_id)
            )
            product = result.scalar_one_or_none()
            
            if not product:
                return False
            
            # Ștergem din coșuri
            await session.execute(
                delete(CartItem).where(CartItem.product_id == product_id)
            )
            
            await session.delete(product)
            await session.commit()
            logger.info(f"Product deleted: {product_id}")
            return True

class CartService:
    @staticmethod
    async def get_cart_items(telegram_id: int) -> List[CartItem]:
        async with async_session() as session:
            # Get user first
            user_result = await session.execute(
                select(User).where(User.telegram_id == telegram_id)
            )
            user = user_result.scalar_one_or_none()
            
            if not user:
                return []
            
            # Get cart items with products
            result = await session.execute(
                select(CartItem, Product)
                .join(Product, CartItem.product_id == Product.id)
                .where(CartItem.user_id == user.id)
                .order_by(CartItem.created_at)
            )
            
            items = []
            for cart_item, product in result:
                cart_item.product = product
                items.append(cart_item)
            
            return items
    
    @staticmethod
    async def add_to_cart(telegram_id: int, product_id: int, quantity: int = 1) -> bool:
        async with async_session() as session:
            user_result = await session.execute(
                select(User).where(User.telegram_id == telegram_id)
            )
            user = user_result.scalar_one_or_none()
            
            if not user:
                return False
            
            product_result = await session.execute(
                select(Product).where(
                    Product.id == product_id,
                    Product.is_active == True
                )
            )
            product = product_result.scalar_one_or_none()
            
            if not product or product.stock < quantity:
                return False
            
            existing = await session.execute(
                select(CartItem).where(
                    CartItem.user_id == user.id,
                    CartItem.product_id == product_id
                )
            )
            existing_item = existing.scalar_one_or_none()
            
            if existing_item:
                if product.stock < existing_item.quantity + quantity:
                    return False
                existing_item.quantity += quantity
            else:
                cart_item = CartItem(
                    user_id=user.id,
                    product_id=product_id,
                    quantity=quantity
                )
                session.add(cart_item)
            
            await session.commit()
            logger.info(f"Added to cart: {telegram_id}, product={product_id}, qty={quantity}")
            return True
    
    @staticmethod
    async def clear_cart(telegram_id: int) -> bool:
        async with async_session() as session:
            user_result = await session.execute(
                select(User).where(User.telegram_id == telegram_id)
            )
            user = user_result.scalar_one_or_none()
            
            if not user:
                return False
            
            await session.execute(
                delete(CartItem).where(CartItem.user_id == user.id)
            )
            await session.commit()
            logger.info(f"Cart cleared for user: {telegram_id}")
            return True

class OrderService:
    @staticmethod
    async def reset_shop_data() -> bool:
        async with async_session() as session:
            try:
                await session.execute(delete(OrderHistory))
                await session.execute(delete(OrderItem))
                await session.execute(delete(Order))
                await session.execute(delete(CartItem))
                await session.execute(delete(CustomerProfile))
                await session.execute(delete(User))
                await session.commit()
                logger.warning("Shop data reset; products were preserved")
                return True
            except Exception as e:
                await session.rollback()
                logger.error(f"Error resetting shop data: {str(e)}")
                return False

    @staticmethod
    async def create_order(telegram_id: int, delivery_data: dict) -> Optional[Order]:
        async with async_session() as session:
            try:
                user_result = await session.execute(
                    select(User).where(User.telegram_id == telegram_id)
                )
                user = user_result.scalar_one_or_none()
                
                if not user:
                    return None
                
                cart_items_result = await session.execute(
                    select(CartItem, Product)
                    .join(Product)
                    .where(CartItem.user_id == user.id)
                )
                cart_items = cart_items_result.all()
                
                if not cart_items:
                    return None
                
                total = 0
                order_items = []
                
                for cart_item, product in cart_items:
                    if product.stock < cart_item.quantity:
                        logger.error(f"Insufficient stock for product {product.id}")
                        return None
                    
                    subtotal = product.price * cart_item.quantity
                    total += subtotal
                    
                    order_items.append({
                        'product_id': product.id,
                        'product_name': product.name,
                        'price': product.price,
                        'quantity': cart_item.quantity,
                        'subtotal': subtotal
                    })
                    
                    product.stock -= cart_item.quantity
                
                last_order_number = await session.execute(
                    select(func.max(Order.order_number))
                )
                order_number = (last_order_number.scalar() or 0) + 1
                
                order = Order(
                    order_number=order_number,
                    user_id=user.id,
                    total=total,
                    status=OrderStatus.NEW.value,
                    full_name=delivery_data['full_name'],
                    postal_code=delivery_data['postal_code'],
                    phone=delivery_data['phone'],
                    district_village=delivery_data['district_village']
                )
                session.add(order)
                await session.flush()
                
                for item_data in order_items:
                    order_item = OrderItem(
                        order_id=order.id,
                        **item_data
                    )
                    session.add(order_item)
                
                history = OrderHistory(
                    order_id=order.id,
                    actor_id=user.id,
                    actor_type="customer",
                    old_status="",
                    new_status=OrderStatus.NEW.value,
                    note="Comandă plasată"
                )
                session.add(history)
                
                for cart_item, _ in cart_items:
                    await session.delete(cart_item)
                
                profile_result = await session.execute(
                    select(CustomerProfile).where(CustomerProfile.user_id == user.id)
                )
                profile = profile_result.scalar_one_or_none()
                
                if profile:
                    profile.full_name = delivery_data['full_name']
                    profile.postal_code = delivery_data['postal_code']
                    profile.phone = delivery_data['phone']
                    profile.district_village = delivery_data['district_village']
                else:
                    profile = CustomerProfile(
                        user_id=user.id,
                        **delivery_data
                    )
                    session.add(profile)
                
                await session.commit()
                await session.refresh(order)
                
                logger.info(f"Order created: #{order.order_number} for user {telegram_id}")
                return order
                
            except Exception as e:
                await session.rollback()
                logger.error(f"Error creating order: {str(e)}")
                return None
    
    @staticmethod
    async def get_user_orders(telegram_id: int) -> List[Order]:
        async with async_session() as session:
            result = await session.execute(
                select(Order)
                .join(User)
                .where(User.telegram_id == telegram_id)
                .order_by(Order.created_at.desc())
            )
            return result.scalars().all()
    
    @staticmethod
    async def get_all_orders() -> List[Order]:
        async with async_session() as session:
            result = await session.execute(
                select(Order).order_by(Order.created_at.desc())
            )
            return result.scalars().all()
    
    @staticmethod
    async def get_orders_by_status(status: str) -> List[Order]:
        async with async_session() as session:
            result = await session.execute(
                select(Order)
                .where(Order.status == status)
                .order_by(Order.created_at.desc())
            )
            return result.scalars().all()
    
    @staticmethod
    async def get_order(order_id: int) -> Optional[Order]:
        async with async_session() as session:
            result = await session.execute(
                select(Order)
                .options(selectinload(Order.items), selectinload(Order.history))
                .where(Order.id == order_id)
            )
            return result.scalar_one_or_none()
    
    @staticmethod
    async def change_order_status(order_id: int, new_status: str, actor_id: int, actor_type: str) -> Optional[Order]:
        async with async_session() as session:
            try:
                order_result = await session.execute(
                    select(Order).where(Order.id == order_id)
                )
                order = order_result.scalar_one_or_none()
                
                if not order:
                    return None
                
                old_status = order.status
                
                valid_transitions = {
                    OrderStatus.NEW.value: [OrderStatus.CONFIRMED.value, OrderStatus.CANCELLED.value],
                    OrderStatus.CONFIRMED.value: [OrderStatus.HANDED_TO_POST.value, OrderStatus.CANCELLED.value],
                    OrderStatus.HANDED_TO_POST.value: [OrderStatus.SHIPPED.value, OrderStatus.CANCELLED.value],
                    OrderStatus.SHIPPED.value: [OrderStatus.RECEIVED.value],
                    OrderStatus.RECEIVED.value: [],
                    OrderStatus.CANCELLED.value: []
                }
                
                if actor_type == "customer":
                    if not (old_status == OrderStatus.SHIPPED.value and new_status == OrderStatus.RECEIVED.value):
                        return None
                elif actor_type == "admin":
                    if new_status not in valid_transitions.get(old_status, []):
                        return None
                else:
                    return None
                
                order.status = new_status
                
                status_notes = {
                    OrderStatus.NEW.value: "Comandă plasată",
                    OrderStatus.CONFIRMED.value: "Comandă confirmată",
                    OrderStatus.HANDED_TO_POST.value: "Predată la Poștă",
                    OrderStatus.SHIPPED.value: "Expediată",
                    OrderStatus.RECEIVED.value: "Colet primit",
                    OrderStatus.CANCELLED.value: "Comandă anulată"
                }
                
                history = OrderHistory(
                    order_id=order.id,
                    actor_id=actor_id,
                    actor_type=actor_type,
                    old_status=old_status,
                    new_status=new_status,
                    note=status_notes.get(new_status, "Status schimbat")
                )
                session.add(history)
                
                if new_status == OrderStatus.CANCELLED.value:
                    for item in order.items:
                        product_result = await session.execute(
                            select(Product).where(Product.id == item.product_id)
                        )
                        product = product_result.scalar_one_or_none()
                        if product:
                            product.stock += item.quantity
                
                await session.commit()
                await session.refresh(order)
                
                logger.info(f"Order #{order.order_number} status changed: {old_status} -> {new_status}")
                return order
                
            except Exception as e:
                await session.rollback()
                logger.error(f"Error changing order status: {str(e)}")
                return None
    
    @staticmethod
    async def get_statistics() -> Dict:
        async with async_session() as session:
            total_orders = await session.execute(
                select(func.count(Order.id))
            )
            total_orders = total_orders.scalar() or 0
            
            status_counts = {}
            for status in OrderStatus:
                count = await session.execute(
                    select(func.count(Order.id)).where(Order.status == status.value)
                )
                status_counts[status.value.lower()] = count.scalar() or 0
            
            total_value = await session.execute(
                select(func.sum(Order.total)).where(Order.status != OrderStatus.CANCELLED.value)
            )
            total_value = total_value.scalar() or 0
            
            today = datetime.now().date()
            today_sales = await session.execute(
                select(func.sum(Order.total)).where(
                    Order.status == OrderStatus.RECEIVED.value,
                    func.date(Order.created_at) == today
                )
            )
            today_sales = today_sales.scalar() or 0
            
            month_start = datetime(today.year, today.month, 1)
            month_sales = await session.execute(
                select(func.sum(Order.total)).where(
                    Order.status == OrderStatus.RECEIVED.value,
                    Order.created_at >= month_start
                )
            )
            month_sales = month_sales.scalar() or 0
            
            avg_order_value = total_value / total_orders if total_orders > 0 else 0
            
            return {
                'total_orders': total_orders,
                'new_orders': status_counts.get('new', 0),
                'confirmed_orders': status_counts.get('confirmed', 0),
                'handed_to_post': status_counts.get('handed_to_post', 0),
                'shipped_orders': status_counts.get('shipped', 0),
                'received_orders': status_counts.get('received', 0),
                'cancelled_orders': status_counts.get('cancelled', 0),
                'total_value': total_value,
                'today_sales': today_sales,
                'month_sales': month_sales,
                'avg_order_value': avg_order_value
            }

class NotificationService:
    @staticmethod
    async def notify_new_order(order: Order, bot: Bot):
        text = (
            f"🆕 COMANDĂ NOUĂ #{order.order_number}\n\n"
            f"👤 {order.full_name}\n"
            f"📱 {order.phone}\n"
            f"📍 {order.district_village}\n"
            f"💰 Total: {order.total:,.0f} MDL"
        )
        for admin_id in ADMIN_IDS:
            try:
                await bot.send_message(chat_id=admin_id, text=text)
            except Exception as e:
                logger.error(f"Error notifying admin {admin_id}: {str(e)}")

    @staticmethod
    async def notify_status_change(order: Order, bot: Bot):
        async with async_session() as session:
            user_result = await session.execute(
                select(User).where(User.id == order.user_id)
            )
            user = user_result.scalar_one_or_none()
            
            if not user:
                return
            
            messages = {
                OrderStatus.CONFIRMED.value: f"✅ Comanda #{order.order_number} a fost confirmată!\n\nPregătim coletul pentru expediere.",
                OrderStatus.HANDED_TO_POST.value: f"📮 Comanda #{order.order_number}\n\nColetul tău a fost predat la Poștă.",
                OrderStatus.SHIPPED.value: f"🚚 Comanda #{order.order_number} a fost expediată!\n\n💳 Plata se efectuează la primirea coletului.\n\nLivrare GRATUITĂ în toată Moldova!",
                OrderStatus.RECEIVED.value: f"✅ Comanda #{order.order_number} a fost finalizată.\n\nMulțumim pentru cumpărături! ❤️",
                OrderStatus.CANCELLED.value: f"❌ Comanda #{order.order_number} a fost anulată.\n\nPentru informații contactează magazinul."
            }
            
            if order.status in messages:
                try:
                    await bot.send_message(
                        chat_id=user.telegram_id,
                        text=messages[order.status]
                    )
                except Exception as e:
                    logger.error(f"Error sending notification: {str(e)}")

# ============ VALIDATORS ============

CUSTOM_EMOJI_IDS = {
    "💵": "5197434882321567830",
    "💰": "5287231198098117669",
    "🔥": "5424972470023104089",
    "📦": "5413879192267805083",
    "🏷️": "5240228673738527951",
    "❌": "5210952531676504517",
    "✅": "5206607081334906820",
    "📍": "5391032818111363540",
    "⚙️": "5341715473882955310",
    "📝": "5395444784611480792",
}


def render_custom_emoji(text: str) -> str:
    for emoji, emoji_id in CUSTOM_EMOJI_IDS.items():
        text = text.replace(
            emoji,
            f'<tg-emoji emoji-id="{emoji_id}">{emoji}</tg-emoji>'
        )
    return text


def get_custom_emoji_entities(text: str) -> List[MessageEntity]:
    entities = []
    for emoji, emoji_id in CUSTOM_EMOJI_IDS.items():
        search_from = 0
        while True:
            position = text.find(emoji, search_from)
            if position == -1:
                break
            prefix = text[:position].encode("utf-16-le")
            value = emoji.encode("utf-16-le")
            entities.append(MessageEntity(
                type="custom_emoji",
                offset=len(prefix) // 2,
                length=len(value) // 2,
                custom_emoji_id=emoji_id,
            ))
            search_from = position + len(emoji)
    return sorted(entities, key=lambda entity: entity.offset or 0)

def validate_phone(phone: str) -> bool:
    if not phone or not isinstance(phone, str):
        return False
    phone = phone.strip()
    pattern = r'^(\+?373|0)[0-9]{8}$'
    return bool(re.fullmatch(pattern, phone))

def validate_postal_code(postal_code: str) -> bool:
    if not postal_code or not isinstance(postal_code, str):
        return False
    postal_code = postal_code.strip()
    pattern = r'^[0-9]{4}$'
    return bool(re.fullmatch(pattern, postal_code))

def validate_name(name: str) -> bool:
    if not name or not isinstance(name, str):
        return False
    return len(name.strip()) >= 3

# ============ HANDLERS ============

router = Router()


@router.errors()
async def handle_telegram_errors(event: ErrorEvent):
    error_text = str(event.exception)
    if isinstance(event.exception, TelegramBadRequest) and (
        "query is too old" in error_text
        or "message is not modified" in error_text
    ):
        logger.warning("Ignored expired or unchanged Telegram callback: %s", error_text)
        return True

    logger.exception("Unhandled Telegram update error", exc_info=event.exception)
    return True

# ===== START =====

@router.message(Command("start"))
async def cmd_start(message: Message):
    user = await UserService.get_or_create_user(
        telegram_id=message.from_user.id,
        username=message.from_user.username,
        first_name=message.from_user.first_name,
        last_name=message.from_user.last_name
    )
    
    is_admin = message.from_user.id in ADMIN_IDS
    
    welcome_text = (
        f"⌚ Bine ai venit la {STORE_NAME}!\n\n"
        "✅ Calitate garantată\n"
        "✅ Prețuri excelente\n"
        "✅ Livrare GRATUITĂ în toată Moldova\n"
        "✅ Plata la primire\n\n"
        "Alege accesoriul perfect pentru tine!"
    )
    
    await message.answer(welcome_text, reply_markup=get_main_keyboard(is_admin))

@router.message(Command("reset8888"))
async def reset_shop(message: Message, state: FSMContext):
    if message.from_user.id not in ADMIN_IDS:
        await message.answer("⛔ Acces interzis!")
        return

    await state.clear()
    await state.set_state(ResetStates.first_confirmation)
    await message.answer(
        "⚠️ Resetarea va șterge utilizatorii, coșurile și comenzile.\n"
        "Produsele vor fi păstrate.\n\n"
        "Confirmarea 1/2: răspundeți cu (Da confirm stergerea datelor) pentru a continua."
    )
    return

@router.message(ResetStates.first_confirmation)
async def reset_first_confirmation(message: Message, state: FSMContext):
    if message.from_user.id not in ADMIN_IDS:
        await state.clear()
        await message.answer("⛔ Acces interzis!")
        return

    if (message.text or "").strip().upper() != "Da confirm stergerea datelor ":
        await state.clear()
        await message.answer("Resetarea a fost anulată. Pentru a începe din nou, scrieți /reset8888.")
        return

    await state.set_state(ResetStates.second_confirmation)
    await message.answer(
        "⚠️ Confirmarea 2/2: resetarea este ireversibilă pentru utilizatori, coșuri și comenzi.\n"
        "Răspundeți din nou cu (Da confirm stergerea datelor) pentru executare."
    )

@router.message(ResetStates.second_confirmation)
async def reset_second_confirmation(message: Message, state: FSMContext):
    if message.from_user.id not in ADMIN_IDS:
        await state.clear()
        await message.answer("⛔ Acces interzis!")
        return

    if (message.text or "").strip().upper() != "Da confirm stergerea datelor":
        await state.clear()
        await message.answer("Resetarea a fost anulată. Pentru a începe din nou, scrieți /reset8888.")
        return

    success = await OrderService.reset_shop_data()
    await state.clear()

    if success:
        await message.answer(
            "✅ Botul a fost resetat. Utilizatorii, coșurile și comenzile au fost șterse.\n"
            "Produsele au fost păstrate. Numerele comenzilor reîncep de la 1."
        )
    else:
        await message.answer("❌ Resetarea a eșuat. Verificați logurile serverului.")

@router.message(Command("cancel"))
async def cmd_cancel(message: Message, state: FSMContext):
    await state.clear()
    await message.answer("❌ Operațiune anulată.", reply_markup=get_main_keyboard(
        message.from_user.id in ADMIN_IDS
    ))

@router.callback_query(F.data == "back_to_main")
async def back_to_main(callback: CallbackQuery):
    is_admin = callback.from_user.id in ADMIN_IDS
    await callback.message.edit_text(
        f"⌚ {STORE_NAME}\n\nMeniu principal:",
        reply_markup=get_main_keyboard(is_admin)
    )
    await callback.answer()

@router.callback_query(F.data == "about")
async def about(callback: CallbackQuery):
    text = (
        f"ℹ️ DESPRE {STORE_NAME.upper()}\n\n"
        f"{STORE_NAME} este magazinul tău online de ceasuri și brățări premium.\n\n"
        "✅ Produse originale\n"
        "✅ Garanție oficială\n"
        "✅ Livrare GRATUITĂ în toată Moldova\n"
        "✅ Plata la primire\n"
        "✅ Suport clienți dedicat\n\n"
        "Oferim o gamă variată de ceasuri și brățări de la branduri renumite."
    )
    await callback.message.edit_text(text, reply_markup=get_back_keyboard())
    await callback.answer()

@router.callback_query(F.data == "contact")
async def contact(callback: CallbackQuery):
    text = (
        f"💬 CONTACT {STORE_NAME.upper()}\n\n"
        "📱 Telefon: +373 68 123 456\n"
        "📧 Email: info@magazinul-tau.md\n"
        "📍 Adresă: Chișinău, Moldova\n\n"
        "🚚 Livrare GRATUITĂ în toată Moldova\n"
        "⏱️ Livrare rapidă în 24-48 ore\n\n"
        "Program de lucru:\n"
        "Luni - Vineri: 9:00 - 18:00\n"
        "Sâmbătă: 10:00 - 15:00\n"
        "Duminică: Închis"
    )
    await callback.message.edit_text(text, reply_markup=get_back_keyboard())
    await callback.answer()

# ===== CATALOG =====

async def render_catalog_page(
    callback: CallbackQuery,
    text: str,
    reply_markup: InlineKeyboardMarkup,
) -> None:
    if callback.message.photo:
        await callback.message.delete()
        await callback.message.answer(text, reply_markup=reply_markup)
        return

    await callback.message.edit_text(text, reply_markup=reply_markup)

@router.callback_query(F.data == "catalog")
async def show_catalog(callback: CallbackQuery):
    categories = await CategoryService.get_all_categories()
    
    if not categories:
        # Adăugăm categorii implicite
        default_categories = ["Ceasuri", "Brățări"]
        for cat in default_categories:
            await CategoryService.add_category(cat)
        categories = await CategoryService.get_all_categories()
    
    await render_catalog_page(
        callback,
        f"⌚ CATALOG {STORE_NAME.upper()}\n\nSelectați o categorie:",
        reply_markup=get_catalog_keyboard(categories)
    )
    await callback.answer()

@router.callback_query(F.data == "offers")
async def show_offers(callback: CallbackQuery):
    products = await ProductService.get_products_with_discount()
    
    if not products:
        await callback.message.edit_text(
            "❌ Nu există oferte disponibile momentan.",
            reply_markup=get_back_keyboard("catalog")
        )
        await callback.answer()
        return
    
    text = f"🔥 OFERTE SPECIALE {STORE_NAME.upper()}\n\n"
    text += "🚚 Livrare GRATUITĂ în toată Moldova!\n\n"
    
    buttons = []
    for i, product in enumerate(products[:10], 1):
        discount = ((product.old_price - product.price) / product.old_price) * 100
        text += f"{i}. ⌚ {product.name}\n"
        text += f"   💰 {product.price:,.0f} MDL (~~{product.old_price:,.0f}~~)\n"
        text += f"   🔥 -{discount:.0f}%\n\n"
        
        buttons.append([InlineKeyboardButton(
            text=f"👀 {product.name}",
            callback_data=f"view_product_{product.id}"
        )])
    
    buttons.append([InlineKeyboardButton(text="⬅️ Înapoi", callback_data="catalog")])
    
    await callback.message.edit_text(
        text,
        reply_markup=InlineKeyboardMarkup(inline_keyboard=buttons)
    )
    await callback.answer()

@router.callback_query(F.data == "category_all")
async def show_all_products(callback: CallbackQuery):
    products = await ProductService.get_active_products()
    
    if not products:
        await callback.message.edit_text(
            "❌ Nu există produse disponibile.",
            reply_markup=get_back_keyboard("catalog")
        )
        await callback.answer()
        return
    
    text = "⌚ TOATE PRODUSELE\n"
    text += "🚚 Livrare GRATUITĂ în toată Moldova!\n\n"
    
    buttons = []
    for i, product in enumerate(products[:10], 1):
        stock_status = "✅" if product.stock > 0 else "❌"
        text += f"{i}. ⌚ {product.name}\n"
        text += f"   💰 {product.price:,.0f} MDL {stock_status}\n\n"
        
        buttons.append([InlineKeyboardButton(
            text=f"👀 {product.name} - {product.price:,.0f} MDL",
            callback_data=f"view_product_{product.id}"
        )])
    
    buttons.append([InlineKeyboardButton(text="⬅️ Înapoi", callback_data="catalog")])
    
    await callback.message.edit_text(
        text,
        reply_markup=InlineKeyboardMarkup(inline_keyboard=buttons)
    )
    await callback.answer()

@router.callback_query(F.data.startswith("category_"))
async def show_category_products(callback: CallbackQuery):
    category = callback.data.replace("category_", "")
    
    products = await ProductService.get_products_by_category(category)
    
    if not products:
        await render_catalog_page(
            callback,
            f"❌ Nu există produse în categoria '{category}'.",
            reply_markup=get_back_keyboard("catalog")
        )
        await callback.answer()
        return
    
    text = f"⌚ CATEGORIA: {category.upper()}\n"
    text += "🚚 Livrare GRATUITĂ în toată Moldova!\n\n"
    
    buttons = []
    for i, product in enumerate(products[:10], 1):
        stock_status = "✅" if product.stock > 0 else "❌"
        text += f"{i}. ⌚ {product.name}\n"
        text += f"   💰 {product.price:,.0f} MDL {stock_status}\n\n"
        
        buttons.append([InlineKeyboardButton(
            text=f"👀 {product.name} - {product.price:,.0f} MDL",
            callback_data=f"view_product_{product.id}"
        )])
    
    buttons.append([InlineKeyboardButton(text="⬅️ Înapoi", callback_data="catalog")])
    
    await render_catalog_page(
        callback,
        text,
        reply_markup=InlineKeyboardMarkup(inline_keyboard=buttons)
    )
    await callback.answer()

@router.callback_query(F.data.startswith("view_product_"))
async def view_product(callback: CallbackQuery):
    product_id = int(callback.data.replace("view_product_", ""))
    product = await ProductService.get_product(product_id)
    
    if not product:
        await callback.answer("Produsul nu a fost găsit", show_alert=True)
        return
    
    text = f"⌚ {product.name}\n\n"
    text += f"💵 {product.price:,.0f} MDL\n"
    
    if product.old_price and product.old_price > 0:
        discount = ((product.old_price - product.price) / product.old_price) * 100
        text += f"~~{product.old_price:,.0f} MDL~~\n"
        text += f"🔥 REDUCERE {discount:.0f}%\n"
    
    if product.stock > 0:
        text += "📦 În stoc\n"
    else:
        text += "❌ Stoc epuizat\n"
    
    text += f"🏷️ Categorie: {product.category}\n"
    text += "🚚 Livrare GRATUITĂ în toată Moldova\n"
    
    if product.features:
        text += f"\n⚙️ Caracteristici:\n{product.features}\n"
    
    if product.description:
        text += f"\n📝 Descriere:\n{product.description}\n"

    caption_entities = get_custom_emoji_entities(text)
    
    keyboard = get_product_keyboard(product.id, product.stock > 0, product.category)
    
    if product.photo_file_id:
        try:
            await callback.message.answer_photo(
                photo=product.photo_file_id,
                caption=text,
                caption_entities=caption_entities,
                reply_markup=keyboard
            )
        except:
            await callback.message.answer(
                text,
                entities=caption_entities,
                reply_markup=keyboard
            )
    else:
        await callback.message.answer(
            text,
            entities=caption_entities,
            reply_markup=keyboard
        )
    
    await callback.answer()

@router.callback_query(F.data.startswith("add_to_cart_"))
async def add_to_cart(callback: CallbackQuery):
    product_id = int(callback.data.replace("add_to_cart_", ""))
    
    success = await CartService.add_to_cart(callback.from_user.id, product_id)
    
    if success:
        await callback.answer("✅ Produs adăugat în coș!", show_alert=True)
    else:
        await callback.answer("❌ Produsul nu este disponibil în stoc!", show_alert=True)

# ===== SEARCH =====

@router.callback_query(F.data == "search")
async def search_prompt(callback: CallbackQuery, state: FSMContext):
    await callback.message.edit_text(
        "🔎 CAUTĂ\n\n"
        "Scrieți numele produsului, categoria sau descrierea:",
        reply_markup=get_back_keyboard()
    )
    await state.set_state(SearchStates.query)
    await callback.answer()

@router.message(SearchStates.query)
async def search_results(message: Message, state: FSMContext):
    query = message.text.strip()
    
    if not query:
        await message.answer("❌ Introduceți un termen de căutare valid.")
        return
    
    products = await ProductService.search_products(query)
    
    if not products:
        await message.answer(
            f"❌ Nu am găsit produse pentru '{query}'.",
            reply_markup=get_back_keyboard()
        )
        await state.clear()
        return
    
    text = f"🔎 REZULTATE PENTRU: {query}\n"
    text += "🚚 Livrare GRATUITĂ în toată Moldova!\n\n"
    
    buttons = []
    for i, product in enumerate(products[:10], 1):
        stock_status = "✅" if product.stock > 0 else "❌"
        text += f"{i}. ⌚ {product.name}\n"
        text += f"   💰 {product.price:,.0f} MDL {stock_status}\n"
        text += f"   🏷️ {product.category}\n\n"
        
        buttons.append([InlineKeyboardButton(
            text=f"👀 {product.name}",
            callback_data=f"view_product_{product.id}"
        )])
    
    buttons.append([InlineKeyboardButton(text="⬅️ Înapoi", callback_data="back_to_main")])
    
    await message.answer(text, reply_markup=InlineKeyboardMarkup(inline_keyboard=buttons))
    await state.clear()

# ===== CART =====

@router.callback_query(F.data == "cart")
async def show_cart(callback: CallbackQuery):
    cart_items = await CartService.get_cart_items(callback.from_user.id)
    
    if not cart_items:
        await callback.message.edit_text(
            "🛒 Coșul este gol.\n\n"
            "Adăugați produse din catalog!",
            reply_markup=get_cart_keyboard(has_items=False)
        )
        await callback.answer()
        return
    
    total = sum(item.product.price * item.quantity for item in cart_items)
    
    text = "🛒 COȘUL MEU\n\n"
    for item in cart_items:
        text += f"⌚ {item.product.name}\n"
        text += f"{item.quantity} × {item.product.price:,.0f} MDL = {item.product.price * item.quantity:,.0f} MDL\n\n"
    
    text += "─" * 20 + "\n"
    text += f"💰 TOTAL: {total:,.0f} MDL\n"
    text += "🚚 Livrare: GRATUITĂ\n"
    text += f"💰 TOTAL FINAL: {total:,.0f} MDL"
    
    await callback.message.edit_text(
        text,
        reply_markup=get_cart_keyboard(has_items=True)
    )
    await callback.answer()

@router.callback_query(F.data == "clear_cart")
async def clear_cart(callback: CallbackQuery):
    await CartService.clear_cart(callback.from_user.id)
    await callback.message.edit_text(
        "🗑️ Coșul a fost golit.",
        reply_markup=get_cart_keyboard(has_items=False)
    )
    await callback.answer("Coș golit ✅", show_alert=True)

# ===== CHECKOUT =====

@router.callback_query(F.data == "checkout")
async def start_checkout(callback: CallbackQuery, state: FSMContext):
    cart_items = await CartService.get_cart_items(callback.from_user.id)

    if not cart_items:
        await callback.answer("Coșul este gol!", show_alert=True)
        return

    for item in cart_items:
        if item.product.stock < item.quantity:
            await callback.answer(
                f"❌ {item.product.name} nu mai este în stoc!\n"
                f"Disponibil: {item.product.stock}",
                show_alert=True
            )
            return

    profile = await UserService.get_customer_profile(callback.from_user.id)

    if profile and profile.full_name and profile.postal_code and profile.phone and profile.district_village:
        await state.update_data(
            full_name=profile.full_name,
            postal_code=profile.postal_code,
            phone=profile.phone,
            district_village=profile.district_village
        )
        await show_order_confirmation(callback, state)
    else:
        await state.clear()
        await callback.message.edit_text(
            "📋 Pentru a plasa comanda, avem nevoie de datele de livrare:\n\n"
            "👤 Nume și prenume:",
            reply_markup=get_back_keyboard("cart")
        )
        await state.set_state(OrderStates.full_name)

    await callback.answer()

async def show_order_confirmation(callback: CallbackQuery, state: FSMContext):
    data = await state.get_data()
    cart_items = await CartService.get_cart_items(callback.from_user.id)
    
    total = sum(item.product.price * item.quantity for item in cart_items)
    
    text = "📦 VERIFICĂ COMANDA\n\n"
    text += f"👤 Nume și prenume:\n{data['full_name']}\n\n"
    text += f"📮 Cod poștal:\n{data['postal_code']}\n\n"
    text += f"📱 Telefon:\n{data['phone']}\n\n"
    text += f"📍 Raion și sat:\n{data['district_village']}\n\n"
    text += "─" * 20 + "\n\n"
    
    for item in cart_items:
        text += f"⌚ {item.product.name} ×{item.quantity}\n"
        text += f"💰 {item.product.price * item.quantity:,.0f} MDL\n\n"
    
    text += "💳 Plata: LA PRIMIRE\n"
    text += "📮 Livrare: Poșta\n"
    text += "🚚 Cost livrare: GRATUIT\n\n"
    text += "─" * 20 + "\n"
    text += f"💰 TOTAL: {total:,.0f} MDL"
    
    keyboard = InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="✅ Confirmă comanda", callback_data="confirm_order")],
        [InlineKeyboardButton(text="✏️ Modifică datele", callback_data="edit_delivery")],
        [InlineKeyboardButton(text="🔙 Înapoi", callback_data="cart")],
    ])
    
    await callback.message.edit_text(text, reply_markup=keyboard)
    await callback.answer()

@router.callback_query(F.data == "edit_delivery")
async def edit_delivery(callback: CallbackQuery, state: FSMContext):
    await state.clear()
    await callback.message.edit_text(
        "📋 Actualizați datele de livrare:\n\n"
        "👤 Nume și prenume:",
        reply_markup=get_back_keyboard("cart")
    )
    await state.set_state(OrderStates.full_name)
    await callback.answer()

@router.message(OrderStates.full_name)
async def process_full_name(message: Message, state: FSMContext):
    name = message.text.strip()
    
    if not validate_name(name):
        await message.answer("❌ Numele trebuie să aibă minim 3 caractere. Încercați din nou:")
        return
    
    await state.update_data(full_name=name)
    await message.answer("✅ Nume salvat!\n\n📮 Cod poștal (4 cifre):")
    await state.set_state(OrderStates.postal_code)

@router.message(OrderStates.postal_code)
async def process_postal_code(message: Message, state: FSMContext):
    postal_code = message.text.strip()
    
    if not validate_postal_code(postal_code):
        await message.answer("❌ Codul poștal trebuie să aibă exact 4 cifre. Încercați din nou:")
        return
    
    await state.update_data(postal_code=postal_code)
    await message.answer("✅ Cod poștal salvat!\n\n📱 Număr de telefon (+373...):")
    await state.set_state(OrderStates.phone)

@router.message(OrderStates.phone)
async def process_phone(message: Message, state: FSMContext):
    phone = message.text.strip()
    
    if not validate_phone(phone):
        await message.answer("❌ Numărul de telefon este invalid. Format: +373XXXXXXXX sau 0XXXXXXXX\nÎncercați din nou:")
        return
    
    await state.update_data(phone=phone)
    await message.answer("✅ Telefon salvat!\n\n📍 Raion și sat:")
    await state.set_state(OrderStates.district_village)

@router.message(OrderStates.district_village)
async def process_district(message: Message, state: FSMContext):
    district = message.text.strip()
    
    if len(district) < 2:
        await message.answer("❌ Adresa este prea scurtă. Încercați din nou:")
        return
    
    await state.update_data(district_village=district)
    
    data = await state.get_data()
    await UserService.save_customer_profile(message.from_user.id, data)
    
    await message.answer("✅ Date salvate! Verificați comanda:")
    
    cart_items = await CartService.get_cart_items(message.from_user.id)
    total = sum(item.product.price * item.quantity for item in cart_items)
    
    text = "📦 VERIFICĂ COMANDA\n\n"
    text += f"👤 {data['full_name']}\n"
    text += f"📮 {data['postal_code']}\n"
    text += f"📱 {data['phone']}\n"
    text += f"📍 {data['district_village']}\n\n"
    text += "─" * 20 + "\n\n"
    
    for item in cart_items:
        text += f"⌚ {item.product.name} ×{item.quantity}\n"
        text += f"💰 {item.product.price * item.quantity:,.0f} MDL\n\n"
    
    text += f"💰 TOTAL: {total:,.0f} MDL\n"
    text += "💳 Plata: LA PRIMIRE\n"
    text += "🚚 Livrare: GRATUITĂ"
    
    keyboard = InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="✅ Confirmă comanda", callback_data="confirm_order")],
        [InlineKeyboardButton(text="✏️ Modifică datele", callback_data="edit_delivery")],
        [InlineKeyboardButton(text="🔙 Înapoi", callback_data="cart")],
    ])
    
    await message.answer(text, reply_markup=keyboard)
    await state.set_state(OrderStates.confirm)

@router.callback_query(F.data == "confirm_order")
async def confirm_order(callback: CallbackQuery, state: FSMContext):
    data = await state.get_data()
    
    order = await OrderService.create_order(callback.from_user.id, data)
    
    if not order:
        await callback.answer("❌ Eroare la plasarea comenzii. Încercați din nou.", show_alert=True)
        return
    
    await state.clear()
    await NotificationService.notify_new_order(order, callback.bot)
    
    text = (
        f"✅ COMANDA #{order.order_number} A FOST PLASATĂ!\n\n"
        f"💰 Total: {order.total:,.0f} MDL\n"
        f"💳 Plata: LA PRIMIRE\n"
        f"🚚 Livrare: GRATUITĂ în toată Moldova\n\n"
        "Veți primi notificări despre statusul comenzii."
    )
    
    await callback.message.edit_text(text, reply_markup=get_back_keyboard())
    await callback.answer("Comandă plasată cu succes! 🎉", show_alert=True)

# ===== ORDERS =====

@router.callback_query(F.data == "my_orders")
async def show_my_orders(callback: CallbackQuery):
    orders = await OrderService.get_user_orders(callback.from_user.id)
    
    if not orders:
        await callback.message.edit_text(
            "📦 Nu aveți comenzi.",
            reply_markup=get_back_keyboard()
        )
        await callback.answer()
        return
    
    text = "📦 COMENZILE MELE\n\n"
    
    buttons = []
    for order in orders[:10]:
        status_emoji = {
            "NEW": "🆕",
            "CONFIRMED": "🟡",
            "HANDED_TO_POST": "📮",
            "SHIPPED": "🚚",
            "RECEIVED": "✅",
            "CANCELLED": "❌"
        }.get(order.status, "❓")
        
        text += f"📦 Comanda #{order.order_number}\n"
        text += f"{status_emoji} Status: {order.status}\n"
        text += f"💰 Total: {order.total:,.0f} MDL\n"
        text += f"📅 Data: {order.created_at.strftime('%d.%m.%Y')}\n\n"
        
        buttons.append([InlineKeyboardButton(
            text=f"👀 Detalii #{order.order_number}",
            callback_data=f"order_detail_{order.id}"
        )])
    
    buttons.append([InlineKeyboardButton(text="⬅️ Înapoi", callback_data="back_to_main")])
    
    await callback.message.edit_text(
        text,
        reply_markup=InlineKeyboardMarkup(inline_keyboard=buttons)
    )
    await callback.answer()

@router.callback_query(F.data.startswith("order_detail_"))
async def show_order_detail(callback: CallbackQuery):
    order_id = int(callback.data.replace("order_detail_", ""))
    order = await OrderService.get_order(order_id)
    
    if not order:
        await callback.answer("Comanda nu a fost găsită", show_alert=True)
        return
    
    user = await UserService.get_or_create_user(callback.from_user.id)
    
    if order.user_id != user.id and callback.from_user.id not in ADMIN_IDS:
        await callback.answer("Acces interzis!", show_alert=True)
        return
    
    text = f"📦 COMANDA #{order.order_number}\n\n"
    text += f"👤 {order.full_name}\n"
    text += f"📮 Cod poștal: {order.postal_code}\n"
    text += f"📱 Telefon: {order.phone}\n"
    text += f"📍 Adresă: {order.district_village}\n\n"
    text += "─" * 20 + "\n\n"
    
    for item in order.items:
        text += f"⌚ {item.product_name}\n"
        text += f"{item.quantity} × {item.price:,.0f} MDL = {item.subtotal:,.0f} MDL\n\n"
    
    text += "─" * 20 + "\n"
    text += f"💰 TOTAL: {order.total:,.0f} MDL\n"
    text += f"💳 Plata: LA PRIMIRE\n"
    text += f"🚚 Livrare: GRATUITĂ\n"
    text += f"📍 Status: {order.status}\n"
    text += f"📅 Data: {order.created_at.strftime('%d.%m.%Y %H:%M')}\n"
    
    if order.history:
        text += "\n📋 ISTORIC:\n"
        for event in order.history:
            actor = "👨‍💼 Admin" if event.actor_type == "admin" else "👤 Client"
            text += f"\n{event.created_at.strftime('%d.%m.%Y %H:%M')}\n"
            text += f"{actor}\n"
            text += f"{event.note}\n"
    
    await callback.message.edit_text(
        text,
        reply_markup=get_order_detail_keyboard(order)
    )
    await callback.answer()

@router.callback_query(F.data.startswith("confirm_received_"))
async def confirm_received(callback: CallbackQuery):
    order_id = int(callback.data.replace("confirm_received_", ""))
    
    order = await OrderService.change_order_status(
        order_id=order_id,
        new_status=OrderStatus.RECEIVED.value,
        actor_id=callback.from_user.id,
        actor_type="customer"
    )
    
    if not order:
        await callback.answer("❌ Eroare la confirmarea primirii!", show_alert=True)
        return
    
    await NotificationService.notify_status_change(order, callback.bot)
    
    await callback.message.edit_text(
        f"✅ Comanda #{order.order_number} a fost finalizată.\n\n"
        "Mulțumim pentru cumpărături! ❤️",
        reply_markup=get_back_keyboard()
    )
    await callback.answer("Comandă confirmată ca primită! ✅", show_alert=True)

# ===== PROFILE =====

@router.callback_query(F.data == "profile")
async def show_profile(callback: CallbackQuery):
    profile = await UserService.get_customer_profile(callback.from_user.id)
    
    if not profile or not profile.full_name:
        text = "👤 PROFIL\n\n"
        text += "Nu aveți un profil complet.\n"
        text += "Completați datele de livrare pentru a plasa comenzi mai rapid."
        
        keyboard = InlineKeyboardMarkup(inline_keyboard=[
            [InlineKeyboardButton(text="📝 Completează profilul", callback_data="edit_profile")],
            [InlineKeyboardButton(text="⬅️ Înapoi", callback_data="back_to_main")],
        ])
    else:
        text = "👤 PROFIL\n\n"
        text += f"👤 Nume: {profile.full_name}\n"
        text += f"📮 Cod poștal: {profile.postal_code}\n"
        text += f"📱 Telefon: {profile.phone}\n"
        text += f"📍 Adresă: {profile.district_village}\n"
        
        keyboard = InlineKeyboardMarkup(inline_keyboard=[
            [InlineKeyboardButton(text="✏️ Editează profilul", callback_data="edit_profile")],
            [InlineKeyboardButton(text="⬅️ Înapoi", callback_data="back_to_main")],
        ])
    
    await callback.message.edit_text(text, reply_markup=keyboard)
    await callback.answer()

@router.callback_query(F.data == "edit_profile")
async def edit_profile(callback: CallbackQuery, state: FSMContext):
    await callback.message.edit_text(
        "📝 COMPLETARE PROFIL\n\n"
        "👤 Nume și prenume:",
        reply_markup=get_back_keyboard("profile")
    )
    await state.set_state(ProfileStates.waiting_for_name)
    await callback.answer()

@router.message(ProfileStates.waiting_for_name)
async def process_profile_name(message: Message, state: FSMContext):
    name = message.text.strip()
    
    if not validate_name(name):
        await message.answer("❌ Numele trebuie să aibă minim 3 caractere. Încercați din nou:")
        return
    
    await state.update_data(full_name=name)
    await message.answer("✅ Nume salvat!\n\n📮 Cod poștal (4 cifre):")
    await state.set_state(ProfileStates.waiting_for_postal_code)

@router.message(ProfileStates.waiting_for_postal_code)
async def process_profile_postal(message: Message, state: FSMContext):
    postal_code = message.text.strip()
    
    if not validate_postal_code(postal_code):
        await message.answer("❌ Codul poștal trebuie să aibă exact 4 cifre. Încercați din nou:")
        return
    
    await state.update_data(postal_code=postal_code)
    await message.answer("✅ Cod poștal salvat!\n\n📱 Număr de telefon (+373...):")
    await state.set_state(ProfileStates.waiting_for_phone)

@router.message(ProfileStates.waiting_for_phone)
async def process_profile_phone(message: Message, state: FSMContext):
    phone = message.text.strip()
    
    if not validate_phone(phone):
        await message.answer("❌ Numărul de telefon este invalid. Format: +373XXXXXXXX sau 0XXXXXXXX\nÎncercați din nou:")
        return
    
    await state.update_data(phone=phone)
    await message.answer("✅ Telefon salvat!\n\n📍 Raion și sat:")
    await state.set_state(ProfileStates.waiting_for_district)

@router.message(ProfileStates.waiting_for_district)
async def process_profile_district(message: Message, state: FSMContext):
    district = message.text.strip()
    
    if len(district) < 2:
        await message.answer("❌ Adresa este prea scurtă. Încercați din nou:")
        return
    
    await state.update_data(district_village=district)
    
    data = await state.get_data()
    await UserService.save_customer_profile(message.from_user.id, data)
    
    await message.answer(
        "✅ PROFIL SALVAT CU SUCCES!\n\n"
        f"👤 {data['full_name']}\n"
        f"📮 {data['postal_code']}\n"
        f"📱 {data['phone']}\n"
        f"📍 {data['district_village']}",
        reply_markup=get_main_keyboard(message.from_user.id in ADMIN_IDS)
    )
    await state.clear()

# ===== ADMIN PANEL =====

@router.callback_query(F.data == "admin_panel")
async def admin_panel(callback: CallbackQuery):
    if callback.from_user.id not in ADMIN_IDS:
        await callback.answer("⛔ Acces interzis!", show_alert=True)
        return
    
    await callback.message.edit_text(
        f"👨‍💼 ADMIN PANEL {STORE_NAME.upper()}\n\nSelectați o opțiune:",
        reply_markup=get_admin_keyboard()
    )
    await callback.answer()

# ===== ADMIN CATEGORIES =====

@router.callback_query(F.data == "admin_categories")
async def admin_categories(callback: CallbackQuery):
    if callback.from_user.id not in ADMIN_IDS:
        await callback.answer("⛔ Acces interzis!", show_alert=True)
        return
    
    await callback.message.edit_text(
        "🏷️ ADMINISTRARE CATEGORII\n\nSelectați o acțiune:",
        reply_markup=get_admin_categories_keyboard()
    )
    await callback.answer()

@router.callback_query(F.data == "admin_add_category")
async def admin_add_category(callback: CallbackQuery, state: FSMContext):
    if callback.from_user.id not in ADMIN_IDS:
        await callback.answer("⛔ Acces interzis!", show_alert=True)
        return
    
    await callback.message.edit_text(
        "➕ ADAUGĂ CATEGORIE\n\n"
        "Introduceți numele categoriei:",
        reply_markup=get_back_keyboard("admin_categories")
    )
    await state.set_state(CategoryStates.waiting_for_name)
    await callback.answer()

@router.message(CategoryStates.waiting_for_name)
async def process_category_name(message: Message, state: FSMContext):
    name = message.text.strip()
    
    if len(name) < 2:
        await message.answer("❌ Numele este prea scurt. Încercați din nou:")
        return
    
    category = await CategoryService.add_category(name)
    
    if category:
        await message.answer(
            f"✅ Categoria '{name}' a fost adăugată!",
            reply_markup=get_admin_categories_keyboard()
        )
    else:
        await message.answer(
            f"❌ Categoria '{name}' există deja!",
            reply_markup=get_admin_categories_keyboard()
        )
    
    await state.clear()

@router.callback_query(F.data == "admin_delete_category")
async def admin_delete_category(callback: CallbackQuery, state: FSMContext):
    if callback.from_user.id not in ADMIN_IDS:
        await callback.answer("⛔ Acces interzis!", show_alert=True)
        return
    
    categories = await CategoryService.get_all_categories()
    
    text = "🗑️ ȘTERGE CATEGORIE\n\n"
    text += "Introduceți numele categoriei:\n\n"
    
    for cat in categories:
        text += f"• {cat.name}\n"
    
    await callback.message.edit_text(
        text,
        reply_markup=get_back_keyboard("admin_categories")
    )
    await state.set_state(CategoryStates.waiting_for_delete)
    await callback.answer()

@router.message(CategoryStates.waiting_for_delete)
async def process_category_delete(message: Message, state: FSMContext):
    name = message.text.strip()
    
    success = await CategoryService.delete_category(name)
    
    if success:
        await message.answer(
            f"✅ Categoria '{name}' a fost ștearsă!",
            reply_markup=get_admin_categories_keyboard()
        )
    else:
        await message.answer(
            f"❌ Categoria '{name}' nu a fost găsită!",
            reply_markup=get_admin_categories_keyboard()
        )
    
    await state.clear()

@router.callback_query(F.data == "admin_list_categories")
async def admin_list_categories(callback: CallbackQuery):
    if callback.from_user.id not in ADMIN_IDS:
        await callback.answer("⛔ Acces interzis!", show_alert=True)
        return
    
    categories = await CategoryService.get_all_categories()
    
    text = "📋 LISTA CATEGORIILOR\n\n"
    
    for i, cat in enumerate(categories, 1):
        # Numără produsele din categorie
        products = await ProductService.get_products_by_category(cat.name)
        text += f"{i}. {cat.name} ({len(products)} produse)\n"
    
    await callback.message.edit_text(
        text,
        reply_markup=get_back_keyboard("admin_categories")
    )
    await callback.answer()

# ===== ADMIN OFFERS =====

@router.callback_query(F.data == "admin_offers")
async def admin_offers(callback: CallbackQuery):
    if callback.from_user.id not in ADMIN_IDS:
        await callback.answer("⛔ Acces interzis!", show_alert=True)
        return
    
    await callback.message.edit_text(
        "🔥 GESTIONARE OFERTE\n\nSelectați o acțiune:",
        reply_markup=get_admin_offers_keyboard()
    )
    await callback.answer()

@router.callback_query(F.data == "admin_set_offer")
async def admin_set_offer(callback: CallbackQuery, state: FSMContext):
    if callback.from_user.id not in ADMIN_IDS:
        await callback.answer("⛔ Acces interzis!", show_alert=True)
        return
    
    products = await ProductService.get_all_products()
    
    text = "🔥 SETEAZĂ OFERTĂ\n\n"
    text += "Introduceți ID-ul produsului:\n\n"
    
    for product in products[:10]:
        text += f"ID: {product.id} - {product.name} - {product.price:.0f} MDL\n"
    
    await callback.message.edit_text(
        text,
        reply_markup=get_back_keyboard("admin_offers")
    )
    await state.set_state(OfferStates.waiting_for_product_id)
    await callback.answer()

@router.message(OfferStates.waiting_for_product_id)
async def process_offer_product(message: Message, state: FSMContext):
    try:
        product_id = int(message.text.strip())
    except ValueError:
        await message.answer("❌ ID invalid! Introduceți un număr:")
        return
    
    product = await ProductService.get_product(product_id)
    
    if not product:
        await message.answer("❌ Produsul nu a fost găsit! Încercați din nou:")
        return
    
    await state.update_data(product_id=product_id)
    await message.answer(
        f"✅ Produs selectat: {product.name}\n"
        f"💰 Preț actual: {product.price:.0f} MDL\n\n"
        "Introduceți noul preț cu reducere:"
    )
    await state.set_state(OfferStates.waiting_for_discount)

@router.message(OfferStates.waiting_for_discount)
async def process_offer_discount(message: Message, state: FSMContext):
    try:
        new_price = float(message.text.strip())
        if new_price <= 0:
            raise ValueError
    except ValueError:
        await message.answer("❌ Preț invalid! Introduceți un număr pozitiv:")
        return
    
    data = await state.get_data()
    product_id = data['product_id']
    
    product = await ProductService.get_product(product_id)
    
    if not product:
        await message.answer("❌ Produsul nu a fost găsit!")
        await state.clear()
        return
    
    # Setăm prețul vechi și noul preț
    updated = await ProductService.update_product(product_id, {
        'old_price': product.price,
        'price': new_price
    })
    
    if updated:
        discount = ((product.price - new_price) / product.price) * 100
        await message.answer(
            f"✅ OFERTĂ SETATĂ!\n\n"
            f"⌚ {updated.name}\n"
            f"💰 Preț nou: {new_price:.0f} MDL\n"
            f"~~Preț vechi: {product.price:.0f} MDL~~\n"
            f"🔥 Reducere: {discount:.0f}%",
            reply_markup=get_admin_offers_keyboard()
        )
    else:
        await message.answer("❌ Eroare la setarea ofertei!")
    
    await state.clear()

@router.callback_query(F.data == "admin_remove_offer")
async def admin_remove_offer(callback: CallbackQuery, state: FSMContext):
    if callback.from_user.id not in ADMIN_IDS:
        await callback.answer("⛔ Acces interzis!", show_alert=True)
        return
    
    products = await ProductService.get_products_with_discount()
    
    if not products:
        await callback.answer("Nu există produse cu oferte!", show_alert=True)
        return
    
    text = "❌ ANULEAZĂ OFERTĂ\n\n"
    text += "Introduceți ID-ul produsului:\n\n"
    
    for product in products:
        text += f"ID: {product.id} - {product.name} - {product.price:.0f} MDL (redus)\n"
    
    await callback.message.edit_text(
        text,
        reply_markup=get_back_keyboard("admin_offers")
    )
    await state.set_state(OfferStates.waiting_for_product_id)
    await callback.answer()

@router.callback_query(F.data == "admin_list_offers")
async def admin_list_offers(callback: CallbackQuery):
    if callback.from_user.id not in ADMIN_IDS:
        await callback.answer("⛔ Acces interzis!", show_alert=True)
        return
    
    products = await ProductService.get_products_with_discount()
    
    if not products:
        await callback.message.edit_text(
            "❌ Nu există produse cu oferte.",
            reply_markup=get_back_keyboard("admin_offers")
        )
        await callback.answer()
        return
    
    text = "🔥 PRODUSE CU OFERTE\n\n"
    
    for product in products:
        discount = ((product.old_price - product.price) / product.old_price) * 100
        text += f"ID: {product.id}\n"
        text += f"⌚ {product.name}\n"
        text += f"💰 {product.price:.0f} MDL (~~{product.old_price:.0f}~~)\n"
        text += f"🔥 -{discount:.0f}%\n\n"
    
    await callback.message.edit_text(
        text,
        reply_markup=get_back_keyboard("admin_offers")
    )
    await callback.answer()

# ===== ADMIN PRODUCTS =====

@router.callback_query(F.data == "admin_products")
async def admin_products(callback: CallbackQuery):
    if callback.from_user.id not in ADMIN_IDS:
        await callback.answer("⛔ Acces interzis!", show_alert=True)
        return
    
    await callback.message.edit_text(
        "⌚ ADMINISTRARE PRODUSE\n\nSelectați o acțiune:",
        reply_markup=get_admin_products_keyboard()
    )
    await callback.answer()

@router.callback_query(F.data == "admin_add_product")
async def admin_add_product(callback: CallbackQuery, state: FSMContext):
    if callback.from_user.id not in ADMIN_IDS:
        await callback.answer("⛔ Acces interzis!", show_alert=True)
        return
    
    categories = await CategoryService.get_all_categories()
    
    await callback.message.edit_text(
        "➕ ADAUGĂ PRODUS NOU\n\n"
        "Introduceți numele produsului:",
        reply_markup=get_back_keyboard("admin_products")
    )
    await state.set_state(ProductStates.waiting_for_name)
    await callback.answer()

@router.message(ProductStates.waiting_for_name)
async def process_product_name(message: Message, state: FSMContext):
    name = message.text.strip()
    
    if len(name) < 2:
        await message.answer("❌ Numele este prea scurt. Încercați din nou:")
        return
    
    await state.update_data(name=name)
    await message.answer(
        "✅ Nume salvat!\n\n"
        "Introduceți descrierea produsului\n"
        "(sau scrieți '0' pentru a omite):"
    )
    await state.set_state(ProductStates.waiting_for_description)

@router.message(ProductStates.waiting_for_description)
async def process_product_description(message: Message, state: FSMContext):
    description = message.text.strip()
    
    if description == '0':
        description = None
    
    await state.update_data(description=description)
    await message.answer(
        "✅ Descriere salvată!\n\n"
        "Introduceți prețul (MDL):"
    )
    await state.set_state(ProductStates.waiting_for_price)

@router.message(ProductStates.waiting_for_price)
async def process_product_price(message: Message, state: FSMContext):
    try:
        price = float(message.text.strip())
        if price <= 0:
            raise ValueError
    except ValueError:
        await message.answer("❌ Preț invalid! Introduceți un număr pozitiv:")
        return
    
    await state.update_data(price=price)
    await message.answer(
        f"✅ Preț salvat: {price:.0f} MDL\n\n"
        "Introduceți prețul vechi pentru reducere\n"
        "(sau 0 dacă nu există):"
    )
    await state.set_state(ProductStates.waiting_for_old_price)

@router.message(ProductStates.waiting_for_old_price)
async def process_product_old_price(message: Message, state: FSMContext):
    try:
        old_price = float(message.text.strip())
        if old_price < 0:
            raise ValueError
    except ValueError:
        await message.answer("❌ Preț invalid! Introduceți un număr pozitiv:")
        return
    
    old_price = old_price if old_price > 0 else None
    await state.update_data(old_price=old_price)
    
    # Afișăm categoriile disponibile
    categories = await CategoryService.get_all_categories()
    text = "✅ Preț vechi salvat!\n\n"
    text += "Introduceți categoria:\n\n"
    text += "Categorii disponibile:\n"
    for cat in categories:
        text += f"• {cat.name}\n"
    
    await message.answer(
        "Selectați categoria produsului:",
        reply_markup=get_product_category_keyboard(categories)
    )
    await state.set_state(ProductStates.waiting_for_category)

@router.callback_query(ProductStates.waiting_for_category, F.data.startswith("product_category_"))
async def process_product_category_callback(callback: CallbackQuery, state: FSMContext):
    try:
        category_id = int(callback.data.replace("product_category_", ""))
    except ValueError:
        await callback.answer("Categorie invalidă!", show_alert=True)
        return

    category = await CategoryService.get_category(category_id)
    if not category:
        await callback.answer("Categoria nu a fost găsită!", show_alert=True)
        return

    await state.update_data(category=category.name)
    await callback.message.edit_text(
        f"✅ Categoria selectată: {category.name}\n\n"
        "Introduceți stocul disponibil:"
    )
    await state.set_state(ProductStates.waiting_for_stock)
    await callback.answer()

@router.callback_query(ProductStates.waiting_for_category, F.data == "cancel_product_creation")
async def cancel_product_creation(callback: CallbackQuery, state: FSMContext):
    await state.clear()
    await callback.message.edit_text(
        "Operațiunea de adăugare a produsului a fost anulată.",
        reply_markup=get_admin_products_keyboard()
    )
    await callback.answer()

@router.message(ProductStates.waiting_for_category)
async def process_product_category(message: Message, state: FSMContext):
    await message.answer("Selectați categoria folosind butoanele de mai sus.")
    return

    category = message.text.strip()
    
    if len(category) < 2:
        await message.answer("❌ Categorie invalidă. Încercați din nou:")
        return
    
    await state.update_data(category=category)
    await message.answer(
        "✅ Categorie salvată!\n\n"
        "Introduceți stocul disponibil:"
    )
    await state.set_state(ProductStates.waiting_for_stock)

@router.message(ProductStates.waiting_for_stock)
async def process_product_stock(message: Message, state: FSMContext):
    try:
        stock = int(message.text.strip())
        if stock < 0:
            raise ValueError
    except ValueError:
        await message.answer("❌ Stoc invalid! Introduceți un număr întreg:")
        return
    
    await state.update_data(stock=stock)
    await message.answer(
        f"✅ Stoc salvat: {stock}\n\n"
        "Introduceți caracteristicile produsului\n"
        "(fiecare pe linie nouă, sau scrieți '0' pentru a omite):"
    )
    await state.set_state(ProductStates.waiting_for_features)

@router.message(ProductStates.waiting_for_features)
async def process_product_features(message: Message, state: FSMContext):
    features = message.text.strip()
    
    if features == '0':
        features = None
    
    await state.update_data(features=features)
    await message.answer(
        "✅ Caracteristici salvate!\n\n"
        "Trimiteți fotografia produsului\n"
        "(sau scrieți '0' pentru a omite):"
    )
    await state.set_state(ProductStates.waiting_for_photo)

@router.message(ProductStates.waiting_for_photo)
async def process_product_photo(message: Message, state: FSMContext):
    data = await state.get_data()
    
    photo_file_id = None
    
    if message.photo:
        photo_file_id = message.photo[-1].file_id
    elif message.text and message.text.strip() != '0':
        await message.answer("❌ Trimiteți o fotografie sau scrieți '0':")
        return
    
    data['photo_file_id'] = photo_file_id
    
    try:
        product = await ProductService.create_product(data)
        
        await message.answer(
            f"✅ PRODUS ADĂUGAT CU SUCCES!\n\n"
            f"⌚ {product.name}\n"
            f"💰 {product.price:.0f} MDL\n"
            f"📦 Stoc: {product.stock}\n"
            f"🏷️ Categorie: {product.category}\n"
            f"ID: {product.id}"
        )
        
        if photo_file_id:
            await message.answer_photo(
                photo=photo_file_id,
                caption=f"⌚ {product.name}"
            )
        
        await state.clear()
        
        await message.answer(
            "👨‍💼 Ce doriți să faceți în continuare?",
            reply_markup=get_admin_products_keyboard()
        )
        
    except Exception as e:
        logger.error(f"Error creating product: {str(e)}")
        await message.answer(f"❌ Eroare la crearea produsului: {str(e)}")
        await state.clear()

@router.callback_query(F.data == "admin_list_products")
async def admin_list_products(callback: CallbackQuery):
    if callback.from_user.id not in ADMIN_IDS:
        await callback.answer("⛔ Acces interzis!", show_alert=True)
        return
    
    products = await ProductService.get_all_products()
    
    if not products:
        await callback.message.edit_text(
            "❌ Nu există produse.",
            reply_markup=get_admin_products_keyboard()
        )
        await callback.answer()
        return
    
    text = "📋 LISTA PRODUSELOR\n\n"
    
    for product in products:
        text += f"ID: {product.id}\n"
        text += f"⌚ {product.name}\n"
        text += f"💰 {product.price:.0f} MDL\n"
        text += f"📦 Stoc: {product.stock}\n"
        text += f"🏷️ {product.category}\n"
        text += f"{'✅ Activ' if product.is_active else '❌ Inactiv'}\n"
        text += "─" * 20 + "\n\n"
    
    buttons = []
    for product in products:
        buttons.append([InlineKeyboardButton(
            text=f"🗑️ Șterge {product.name}",
            callback_data=f"admin_delete_{product.id}"
        )])
    
    buttons.append([InlineKeyboardButton(text="⬅️ Înapoi", callback_data="admin_products")])
    
    await callback.message.edit_text(
        text[:4000],
        reply_markup=InlineKeyboardMarkup(inline_keyboard=buttons[:10] + [[InlineKeyboardButton(text="⬅️ Înapoi", callback_data="admin_products")]])
    )
    await callback.answer()

@router.callback_query(F.data == "admin_delete_product")
async def admin_delete_product_prompt(callback: CallbackQuery, state: FSMContext):
    if callback.from_user.id not in ADMIN_IDS:
        await callback.answer("⛔ Acces interzis!", show_alert=True)
        return
    
    products = await ProductService.get_all_products()
    
    if not products:
        await callback.answer("Nu există produse de șters!", show_alert=True)
        return
    
    text = "🗑️ ȘTERGE PRODUS\n\n"
    text += "Introduceți ID-ul produsului:\n\n"
    
    for product in products[:10]:
        text += f"ID: {product.id} - {product.name}\n"
    
    await callback.message.edit_text(
        text,
        reply_markup=get_back_keyboard("admin_products")
    )
    await state.set_state(ProductStates.waiting_for_product_id)
    await callback.answer()

@router.message(ProductStates.waiting_for_product_id)
async def process_delete_product(message: Message, state: FSMContext):
    try:
        product_id = int(message.text.strip())
    except ValueError:
        await message.answer("❌ ID invalid! Introduceți un număr:")
        return
    
    product = await ProductService.get_product(product_id)
    
    if not product:
        await message.answer("❌ Produsul nu a fost găsit! Încercați din nou:")
        return
    
    success = await ProductService.delete_product(product_id)
    
    if success:
        await message.answer(
            f"✅ Produsul '{product.name}' a fost șters cu succes!",
            reply_markup=get_admin_products_keyboard()
        )
    else:
        await message.answer(
            "❌ Eroare la ștergerea produsului!",
            reply_markup=get_admin_products_keyboard()
        )
    
    await state.clear()

@router.callback_query(F.data.startswith("admin_delete_"))
async def admin_delete_product_quick(callback: CallbackQuery):
    if callback.from_user.id not in ADMIN_IDS:
        await callback.answer("⛔ Acces interzis!", show_alert=True)
        return
    
    product_id = int(callback.data.replace("admin_delete_", ""))
    product = await ProductService.get_product(product_id)
    
    if not product:
        await callback.answer("Produsul nu a fost găsit!", show_alert=True)
        return
    
    success = await ProductService.delete_product(product_id)
    
    if success:
        await callback.answer(f"✅ {product.name} a fost șters!", show_alert=True)
        await admin_list_products(callback)
    else:
        await callback.answer("❌ Eroare la ștergere!", show_alert=True)

@router.callback_query(F.data == "admin_update_price")
async def admin_update_price_prompt(callback: CallbackQuery, state: FSMContext):
    if callback.from_user.id not in ADMIN_IDS:
        await callback.answer("⛔ Acces interzis!", show_alert=True)
        return
    
    products = await ProductService.get_all_products()
    
    text = "💰 MODIFICĂ PREȚ\n\n"
    text += "Introduceți ID-ul produsului și noul preț:\n"
    text += "Format: ID PRET\n"
    text += "Exemplu: 1 1999\n\n"
    
    for product in products[:10]:
        text += f"ID: {product.id} - {product.name} - {product.price:.0f} MDL\n"
    
    await callback.message.edit_text(
        text,
        reply_markup=get_back_keyboard("admin_products")
    )
    await state.set_state(ProductStates.waiting_for_new_price)
    await callback.answer()

@router.message(ProductStates.waiting_for_new_price)
async def process_update_price(message: Message, state: FSMContext):
    parts = message.text.strip().split()
    
    if len(parts) != 2:
        await message.answer("❌ Format invalid! Folosiți: ID PRET\nExemplu: 1 1999")
        return
    
    try:
        product_id = int(parts[0])
        new_price = float(parts[1])
    except ValueError:
        await message.answer("❌ Valori invalide! Folosiți: ID PRET\nExemplu: 1 1999")
        return
    
    product = await ProductService.get_product(product_id)
    
    if not product:
        await message.answer("❌ Produsul nu a fost găsit!")
        return
    
    updated = await ProductService.update_product(product_id, {'price': new_price})
    
    if updated:
        await message.answer(
            f"✅ Preț actualizat!\n\n"
            f"⌚ {updated.name}\n"
            f"💰 {updated.price:.0f} MDL",
            reply_markup=get_admin_products_keyboard()
        )
    else:
        await message.answer("❌ Eroare la actualizarea prețului!")
    
    await state.clear()

@router.callback_query(F.data == "admin_update_stock")
async def admin_update_stock_prompt(callback: CallbackQuery, state: FSMContext):
    if callback.from_user.id not in ADMIN_IDS:
        await callback.answer("⛔ Acces interzis!", show_alert=True)
        return
    
    products = await ProductService.get_all_products()
    
    text = "📦 MODIFICĂ STOC\n\n"
    text += "Introduceți ID-ul produsului și noul stoc:\n"
    text += "Format: ID STOC\n"
    text += "Exemplu: 1 10\n\n"
    
    for product in products[:10]:
        text += f"ID: {product.id} - {product.name} - Stoc: {product.stock}\n"
    
    await callback.message.edit_text(
        text,
        reply_markup=get_back_keyboard("admin_products")
    )
    await state.set_state(ProductStates.waiting_for_new_stock)
    await callback.answer()

@router.message(ProductStates.waiting_for_new_stock)
async def process_update_stock(message: Message, state: FSMContext):
    parts = message.text.strip().split()
    
    if len(parts) != 2:
        await message.answer("❌ Format invalid! Folosiți: ID STOC\nExemplu: 1 10")
        return
    
    try:
        product_id = int(parts[0])
        new_stock = int(parts[1])
    except ValueError:
        await message.answer("❌ Valori invalide! Folosiți: ID STOC\nExemplu: 1 10")
        return
    
    product = await ProductService.get_product(product_id)
    
    if not product:
        await message.answer("❌ Produsul nu a fost găsit!")
        return
    
    updated = await ProductService.update_product(product_id, {'stock': new_stock})
    
    if updated:
        await message.answer(
            f"✅ Stoc actualizat!\n\n"
            f"⌚ {updated.name}\n"
            f"📦 Stoc: {updated.stock}",
            reply_markup=get_admin_products_keyboard()
        )
    else:
        await message.answer("❌ Eroare la actualizarea stocului!")
    
    await state.clear()

# ===== ADMIN ORDERS =====

@router.callback_query(F.data == "admin_orders")
async def admin_orders(callback: CallbackQuery):
    if callback.from_user.id not in ADMIN_IDS:
        await callback.answer("⛔ Acces interzis!", show_alert=True)
        return
    
    await callback.message.edit_text(
        "📦 ADMINISTRARE COMENZI\n\nSelectați o categorie:",
        reply_markup=get_admin_orders_keyboard()
    )
    await callback.answer()

@router.callback_query(F.data == "admin_all_orders")
async def admin_all_orders(callback: CallbackQuery):
    if callback.from_user.id not in ADMIN_IDS:
        await callback.answer("⛔ Acces interzis!", show_alert=True)
        return
    
    orders = await OrderService.get_all_orders()
    
    if not orders:
        await callback.message.edit_text(
            "❌ Nu există comenzi.",
            reply_markup=get_admin_orders_keyboard()
        )
        await callback.answer()
        return
    
    text = "📋 TOATE COMENZILE\n\n"
    
    buttons = []
    for order in orders[:10]:
        text += f"#{order.order_number} - {order.full_name}\n"
        text += f"Status: {order.status} | Total: {order.total:.0f} MDL\n"
        text += f"Data: {order.created_at.strftime('%d.%m.%Y')}\n\n"
        
        buttons.append([InlineKeyboardButton(
            text=f"📦 #{order.order_number} - {order.status}",
            callback_data=f"admin_order_detail_{order.id}"
        )])
    
    buttons.append([InlineKeyboardButton(text="⬅️ Înapoi", callback_data="admin_orders")])
    
    await callback.message.edit_text(
        text[:4000],
        reply_markup=InlineKeyboardMarkup(inline_keyboard=buttons)
    )
    await callback.answer()

@router.callback_query(F.data.startswith("admin_orders_"))
async def admin_orders_by_status(callback: CallbackQuery):
    if callback.from_user.id not in ADMIN_IDS:
        await callback.answer("⛔ Acces interzis!", show_alert=True)
        return
    
    status_map = {
        "new": OrderStatus.NEW.value,
        "confirmed": OrderStatus.CONFIRMED.value,
        "post": OrderStatus.HANDED_TO_POST.value,
        "shipped": OrderStatus.SHIPPED.value,
        "received": OrderStatus.RECEIVED.value,
        "cancelled": OrderStatus.CANCELLED.value
    }
    
    status_key = callback.data.replace("admin_orders_", "")
    status = status_map.get(status_key)
    
    if not status:
        await callback.answer("Status invalid!", show_alert=True)
        return
    
    orders = await OrderService.get_orders_by_status(status)
    
    if not orders:
        await callback.message.edit_text(
            f"❌ Nu există comenzi cu statusul {status}.",
            reply_markup=get_admin_orders_keyboard()
        )
        await callback.answer()
        return
    
    text = f"📦 COMENZI: {status}\n\n"
    
    buttons = []
    for order in orders:
        text += f"#{order.order_number} - {order.full_name}\n"
        text += f"Total: {order.total:.0f} MDL\n"
        text += f"Data: {order.created_at.strftime('%d.%m.%Y')}\n\n"
        
        buttons.append([InlineKeyboardButton(
            text=f"📦 #{order.order_number}",
            callback_data=f"admin_order_detail_{order.id}"
        )])
    
    buttons.append([InlineKeyboardButton(text="⬅️ Înapoi", callback_data="admin_orders")])
    
    await callback.message.edit_text(
        text[:4000],
        reply_markup=InlineKeyboardMarkup(inline_keyboard=buttons)
    )
    await callback.answer()

@router.callback_query(F.data.startswith("admin_order_detail_"))
async def admin_order_detail(callback: CallbackQuery):
    if callback.from_user.id not in ADMIN_IDS:
        await callback.answer("⛔ Acces interzis!", show_alert=True)
        return
    
    if callback.data.startswith("admin_status_"):
        order_id = int(callback.data[len("admin_status_"):].split("_", 1)[0])
    else:
        order_id = int(callback.data.replace("admin_order_detail_", ""))
    order = await OrderService.get_order(order_id)
    
    if not order:
        await callback.answer("Comanda nu a fost găsită", show_alert=True)
        return
    
    text = f"📦 COMANDA #{order.order_number}\n\n"
    text += f"👤 {order.full_name}\n"
    text += f"📮 {order.postal_code}\n"
    text += f"📱 {order.phone}\n"
    text += f"📍 {order.district_village}\n\n"
    text += "─" * 20 + "\n\n"
    
    for item in order.items:
        text += f"⌚ {item.product_name}\n"
        text += f"{item.quantity} × {item.price:.0f} MDL = {item.subtotal:.0f} MDL\n\n"
    
    text += "─" * 20 + "\n"
    text += f"💰 TOTAL: {order.total:.0f} MDL\n"
    text += f"💳 Plata: LA PRIMIRE\n"
    text += f"🚚 Livrare: GRATUITĂ\n"
    text += f"📍 Status: {order.status}\n"
    text += f"📅 Data: {order.created_at.strftime('%d.%m.%Y %H:%M')}\n"
    
    buttons = []
    
    if order.status == OrderStatus.NEW.value:
        buttons.append([InlineKeyboardButton(
            text="✅ Confirmă comanda",
            callback_data=f"admin_status_{order.id}_CONFIRMED"
        )])
        buttons.append([InlineKeyboardButton(
            text="❌ Anulează comanda",
            callback_data=f"admin_status_{order.id}_CANCELLED"
        )])
    elif order.status == OrderStatus.CONFIRMED.value:
        buttons.append([InlineKeyboardButton(
            text="📮 Predă la Poștă",
            callback_data=f"admin_status_{order.id}_HANDED_TO_POST"
        )])
        buttons.append([InlineKeyboardButton(
            text="❌ Anulează comanda",
            callback_data=f"admin_status_{order.id}_CANCELLED"
        )])
    elif order.status == OrderStatus.HANDED_TO_POST.value:
        buttons.append([InlineKeyboardButton(
            text="🚚 Marchează ca expediat",
            callback_data=f"admin_status_{order.id}_SHIPPED"
        )])
        buttons.append([InlineKeyboardButton(
            text="❌ Anulează comanda",
            callback_data=f"admin_status_{order.id}_CANCELLED"
        )])
    
    buttons.append([InlineKeyboardButton(text="⬅️ Înapoi", callback_data="admin_orders")])
    
    await callback.message.edit_text(
        text,
        reply_markup=InlineKeyboardMarkup(inline_keyboard=buttons)
    )
    await callback.answer()

@router.callback_query(F.data.startswith("admin_status_"))
async def admin_change_status(callback: CallbackQuery):
    if callback.from_user.id not in ADMIN_IDS:
        await callback.answer("⛔ Acces interzis!", show_alert=True)
        return

    payload = callback.data[len("admin_status_") :]
    order_id_str, separator, new_status = payload.partition("_")

    if not separator or not order_id_str or not new_status:
        await callback.answer("❌ Date invalide pentru status!", show_alert=True)
        return

    try:
        order_id = int(order_id_str)
    except ValueError:
        await callback.answer("❌ ID comandă invalid!", show_alert=True)
        return

    order = await OrderService.change_order_status(
        order_id=order_id,
        new_status=new_status,
        actor_id=callback.from_user.id,
        actor_type="admin"
    )
    
    if not order:
        await callback.answer("❌ Eroare la schimbarea statusului!", show_alert=True)
        return
    
    await NotificationService.notify_status_change(order, callback.bot)
    
    await callback.answer(f"✅ Status schimbat: {new_status}", show_alert=True)
    
    await admin_order_detail(callback)

# ===== ADMIN CLIENTS =====

@router.callback_query(F.data == "admin_clients")
async def admin_clients(callback: CallbackQuery):
    if callback.from_user.id not in ADMIN_IDS:
        await callback.answer("⛔ Acces interzis!", show_alert=True)
        return
    
    clients = await UserService.get_all_clients()
    
    if not clients:
        await callback.message.edit_text(
            "❌ Nu există clienți.",
            reply_markup=get_back_keyboard("admin_panel")
        )
        await callback.answer()
        return
    
    text = "👥 CLIENȚI ÎNREGISTRAȚI\n\n"
    text += f"Total clienți: {len(clients)}\n\n"
    
    for client in clients[:20]:
        text += f"ID: {client.id}\n"
        text += f"👤 {client.first_name or 'N/A'} {client.last_name or ''}\n"
        text += f"📱 Telegram ID: {client.telegram_id}\n"
        if client.username:
            text += f"👤 Username: @{client.username}\n"
        text += "─" * 20 + "\n"
    
    await callback.message.edit_text(
        text[:4000],
        reply_markup=get_back_keyboard("admin_panel")
    )
    await callback.answer()

# ===== ADMIN STATISTICS =====

@router.callback_query(F.data == "admin_statistics")
async def admin_statistics(callback: CallbackQuery):
    if callback.from_user.id not in ADMIN_IDS:
        await callback.answer("⛔ Acces interzis!", show_alert=True)
        return
    
    stats = await OrderService.get_statistics()
    
    text = f"📊 STATISTICI {STORE_NAME.upper()}\n\n"
    text += f"📦 Comenzi totale: {stats['total_orders']}\n"
    text += f"🆕 Noi: {stats['new_orders']}\n"
    text += f"🟡 Confirmate: {stats['confirmed_orders']}\n"
    text += f"📮 La Poștă: {stats['handed_to_post']}\n"
    text += f"🚚 Expediate: {stats['shipped_orders']}\n"
    text += f"✅ Finalizate: {stats['received_orders']}\n"
    text += f"❌ Anulate: {stats['cancelled_orders']}\n\n"
    text += f"💰 Valoarea comenzilor:\n{stats['total_value']:,.0f} MDL\n\n"
    
    if stats['today_sales'] > 0:
        text += f"📈 Vânzări azi: {stats['today_sales']:,.0f} MDL\n"
    
    if stats['month_sales'] > 0:
        text += f"📈 Vânzări luna aceasta: {stats['month_sales']:,.0f} MDL\n"
    
    if stats['avg_order_value'] > 0:
        text += f"💰 Valoare medie comandă: {stats['avg_order_value']:,.0f} MDL\n"
    
    await callback.message.edit_text(
        text,
        reply_markup=get_back_keyboard("admin_panel")
    )
    await callback.answer()

# ===== MAIN =====

async def init_db():
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
    
    # Adăugăm categorii implicite dacă nu există
    async with async_session() as session:
        result = await session.execute(select(Category))
        categories = result.scalars().all()
        
        if not categories:
            default_categories = ["Ceasuri", "Brățări"]
            for cat_name in default_categories:
                category = Category(name=cat_name)
                session.add(category)
            await session.commit()
            logger.info("Default categories created: Ceasuri, Brățări")
    
    logger.info("Database initialized")


def backup_database() -> Optional[Path]:
    if not DATABASE_URL.startswith("sqlite"):
        return None

    database_path = Path(DATABASE_URL.rsplit("///", 1)[-1])
    if not database_path.exists():
        return None

    BACKUP_DIR.mkdir(parents=True, exist_ok=True)
    timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    backup_path = BACKUP_DIR / f"{database_path.stem}_{timestamp}.db"
    shutil.copy2(database_path, backup_path)
    return backup_path

async def main():
    if not acquire_single_instance():
        logger.error("Another store bot instance is already running.")
        return

    logger.info("Starting %s Bot...", STORE_NAME)
    
    backup_path = backup_database()
    if backup_path:
        logger.info(f"Database backup created: {backup_path}")
    await init_db()
    
    bot = Bot(
        token=BOT_TOKEN,
        default=DefaultBotProperties(parse_mode=ParseMode.HTML)
    )
    dp = Dispatcher(storage=MemoryStorage())
    
    dp.include_router(router)
    
    logger.info("%s Bot started successfully!", STORE_NAME)
    try:
        await dp.start_polling(bot)
    except TelegramUnauthorizedError:
        logger.error("BOT_TOKEN este invalid sau a fost revocat. Actualizează .env din BotFather.")
    finally:
        await bot.session.close()

if __name__ == "__main__":
    if not BOT_TOKEN:
        logger.error("BOT_TOKEN nu este setat în .env!")
        exit(1)
    if not ADMIN_IDS:
        logger.error("ADMIN_IDS nu este setat corect în .env!")
        exit(1)
    
    asyncio.run(main())
