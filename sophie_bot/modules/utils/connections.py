# Copyright (C) 2018 - 2020 MrYacha. All rights reserved. Source code available under the AGPL.
# Copyright (C) 2019 Aiogram
#
# This file is part of SophieBot.
#
# This program is free software: you can redistribute it and/or modify
# it under the terms of the GNU Affero General Public License as
# published by the Free Software Foundation, either version 3 of the
# License, or (at your option) any later version.

# This program is distributed in the hope that it will be useful,
# but WITHOUT ANY WARRANTY; without even the implied warranty of
# MERCHANTABILITY or FITNESS FOR A PARTICULAR PURPOSE.  See the
# GNU Affero General Public License for more details.

# You should have received a copy of the GNU Affero General Public License
# along with this program.  If not, see <http://www.gnu.org/licenses/>.

from sophie_bot.modules.utils.user_details import is_user_admin
from sophie_bot.services.mongo import db
from sophie_bot.services.redis import redis


async def get_connected_chat(message, admin=False, only_groups=False, from_id=None):
    # admin - Require admin rights in connected chat
    # only_in_groups - disable command when bot's pm not connected to any chat
    real_chat_id = message.chat.id
    user_id = from_id or message.from_user.id
    key = 'connection_cache_' + str(user_id)

    if not message.chat.type == 'private':
        _chat = await db.chat_list.find_one({'chat_id': real_chat_id})
        chat_title = _chat['chat_title'] if _chat is not None else message.chat.title
        # On some strange cases such as Database is fresh or new ; it doesn't contain chat data
        # Only to "handle" the error, we do the above workaround - getting chat title from the update
        return {'status': 'chat', 'chat_id': real_chat_id, 'chat_title': chat_title}

    # Cached
    if cached := redis.hgetall(key):
        cached['status'] = True
        cached['chat_id'] = int(cached['chat_id'])
        return cached

    # if pm and not connected
    if not (connected := await db.connections.find_one({'user_id': user_id})) or 'chat_id' not in connected:
        if only_groups:
            return {'status': None, 'err_msg': 'usage_only_in_groups'}
        else:
            return {'status': 'private', 'chat_id': user_id, 'chat_title': 'Local chat'}

    chat_id = connected['chat_id']

    # Get chats where user was detected and check if user in connected chat
    # TODO: Really get the user and check on banned
    user_chats = (await db.user_list.find_one({'user_id': user_id}))['chats']
    if chat_id not in user_chats:
        return {'status': None, 'err_msg': 'not_in_chat'}

    chat_title = (await db.chat_list.find_one({'chat_id': chat_id}))['chat_title']

    # Admin rights check if admin=True
    if admin is True and not (user_admin := (await is_user_admin(chat_id, user_id))):
        return {'status': None, 'err_msg': 'u_should_be_admin'}

    # Check on /allowusersconnect enabled
    if settings := await db.chat_connection_settings.find_one({'chat_id': chat_id}):
        if 'allow_users_connect' in settings and settings['allow_users_connect'] is False and not user_admin:
            return {'status': None, 'err_msg': 'conn_not_allowed'}

    data = {
        'status': True,
        'chat_id': chat_id,
        'chat_title': chat_title
    }

    # Cache connection status for 15 minutes
    cached = data
    cached['status'] = 1
    redis.hmset(key, cached)
    redis.expire(key, 900)

    return data


def chat_connection(**dec_kwargs):
    def wrapped(func):
        async def wrapped_1(*args, **kwargs):

            message = args[0]
            from_id = None
            if hasattr(message, 'message'):
                from_id = message.from_user.id
                message = message.message

            if (check := await get_connected_chat(message, from_id=from_id, **dec_kwargs))['status'] is None:
                await message.reply(check['err_msg'])
                return
            else:
                return await func(*args, check, **kwargs)

        return wrapped_1

    return wrapped


async def set_connected_chat(user_id, chat_id):
    if not chat_id:
        await db.connections.update_one({'user_id': user_id}, {"$unset": {'chat_id': 1}}, upsert=True)
        key = 'connection_cache_' + str(user_id)
        redis.delete(key)
        return

    return await db.connections.update_one(
        {'user_id': user_id},
        {
            "$set": {'user_id': user_id, 'chat_id': chat_id},
            "$addToSet": {'history': {'$each': [chat_id]}}
        },
        upsert=True
    )
