import os
import logging
import math
import sqlite3
import datetime

from telegram.ext import Updater, CommandHandler

walks_notification_interval_minutes = 20
walks_check_interval_seconds = 60
desired_walks_interval_hours = 5
group_chat_id = -663974916
token = os.getenv('TELEGRAM_TOKEN')

walk_message = "O {name} foi-me passear 🐕"
walk_stats_message = "{name} - {count} passeios ({percentage}%)"
no_walks_stats_message = "Nao ha passeios"


def needs_walks_message(hours_fractional):
    if hours_fractional is math.inf:
        return "Nunca fui passear... 🥺"

    hours = int(hours_fractional)
    minutes = int((hours_fractional - hours) * 60)

    if hours > 0 and minutes > 0:
        return "Nao vou passear ha {} horas e {} minutos... 🥺".format(hours, minutes)
    elif hours == 0 and minutes > 0:
        return "Nao vou passear ha {} minutos... 🥺".format(minutes)
    elif hours > 0 and minutes == 0:
        return "Nao vou passear ha {} horas... 🥺".format(hours)
    else:
        raise ValueError(f"Invalid hours {hours_fractional}")


class NotificationThrottler:
    def __init__(self, interval_minutes):
        self.interval = datetime.timedelta(minutes=interval_minutes)
        self.last_notification_time = None

    def should_notify(self):
        if no_previous_notification := self.last_notification_time is None:
            return True
        else:
            return datetime.datetime.now() - self.last_notification_time > self.interval

    def timestamp_sent_notification(self):
        if not self.should_notify():
            raise ValueError(
                "Already notified at {}".format(self.last_notification_time)
            )
        self.last_notification_time = datetime.datetime.now()


def should_supress_notification():
    now = datetime.datetime.now()
    return 5 < now.hour <= 8


con = sqlite3.connect(
    "toby.db",
    check_same_thread=False,
    detect_types=sqlite3.PARSE_DECLTYPES | sqlite3.PARSE_COLNAMES,
)


def save_walk(walker_id, first_name):
    timestamp = datetime.datetime.now()

    c = con.cursor()
    c.execute(
        """
        insert or ignore into walkers values (?, ?) 
    """,
        (walker_id, first_name),
    )
    c.execute(
        """
        insert into walks values (?, ?) 
    """,
        (timestamp, walker_id),
    )
    con.commit()
    c.close()


def last_walk_elapsed_hours():
    c = con.cursor()
    c.execute(
        """
        select date from walks order by date desc limit 1
        """
    )
    result = c.fetchone()
    c.close()

    if not result:
        return math.inf
    else:
        (last_date,) = result
        return (datetime.datetime.now() - last_date).total_seconds() / 3600


def statistics():
    c = con.cursor()
    rows = list(c.execute(
        """
        select
            walkers.first_name,
            count(walks.walker_id),
            count(walks.walker_id) / (select count(*) from walks) * 100
        from walks
        left join walkers on walks.walker_id = walkers.id
        group by walker_id;
       """
    ))
    c.close()

    return rows


notification_throttler = NotificationThrottler(
    interval_minutes=walks_notification_interval_minutes
)

updater = Updater(token=token, use_context=True)
dispatcher = updater.dispatcher
job_queue = updater.job_queue


def check_for_walks(context):
    elapsed_hours = last_walk_elapsed_hours()
    if (
        elapsed_hours > desired_walks_interval_hours
        and notification_throttler.should_notify()
        and not should_supress_notification()
    ):
        message = needs_walks_message(elapsed_hours)

        context.bot.send_message(chat_id=group_chat_id, text=message)
        notification_throttler.timestamp_sent_notification()


job_queue.run_repeating(check_for_walks, interval=walks_check_interval_seconds, first=1)


def walk(update, context):
    sender = update.message.from_user
    walker_id = sender.id
    first_name = sender.first_name

    save_walk(walker_id, first_name)

    response = walk_message.format(name=first_name)
    context.bot.send_message(chat_id=update.effective_chat.id, text=response)


def stats(update, context):
    message_lines = []
    for first_name, walk_count, walk_percentage in statistics():
        message_line = walk_stats_message.format(
            name=first_name, count=walk_count, percentage=walk_percentage
        )
        message_lines.append(message_line)
    else:
        message_lines.append(no_walks_stats_message)

    message = "\n".join(message_lines)

    context.bot.send_message(chat_id=group_chat_id, text=message)


walk_handler = CommandHandler("walk", walk)
dispatcher.add_handler(walk_handler)

stats_handler = CommandHandler("stats", stats)
dispatcher.add_handler(stats_handler)

if __name__ == "__main__":
    c = con.cursor()
    c.executescript(
        """
        create table if not exists walkers (id text primary key, first_name text);
        create table if not exists walks (date timestamp, walker_id text, foreign key (walker_id) references walkers(id));
        """
    )
    con.commit()
    c.close()

    logging.basicConfig(
        format="%(asctime)s - %(name)s - %(levelname)s - %(message)s",
        level=logging.INFO,
    )

    updater.start_polling()
