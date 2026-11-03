# Appointment booking

Each client has an appointment book under **Clients → (client) → Booking**. With it on, every chat agent of that client can offer free times, book one and cancel one, right in the conversation.

## Setting up the book

- **Agents book appointments**: turns the book on. It needs at least one day with hours.
- **Bookable hours**: per weekday, the hours appointments can start in, read in the client's timezone (set under **Details**).
- **Each appointment lasts**: the length, in minutes. Free times are offered on that grid from the start of each day's hours.
- **Appointments at the same time**: how many people can be seen at once (1 by default).
- **Minimum notice** and **Book up to**: the earliest and latest an appointment can be booked.
- **Place or directions**: the agent shares it when it confirms, and the reminder carries it.
- **Send a reminder**: a message a set number of hours before (24 by default) in the same chat.

## What the agent does

The agent receives three tools:

| Tool | What it does |
| --- | --- |
| `check_availability` | Lists free start times for the next days. |
| `book_appointment` | Books a free time with the person's name and optional notes. |
| `cancel_appointment` | Cancels one of the person's upcoming appointments. |

The agent is told the business's current date and time, to check availability before offering times, to confirm the day, time and name before booking, and never to say an appointment is booked unless the tool confirmed it. To move an appointment it cancels the old one and books the new one. The agent also sees the person's upcoming appointments.

The playground rehearses the tools with real free times, but books nothing. Phone calls do not book yet.

## Reminders

Reminders go out through the conversation's channel (WhatsApp, WhatsApp Cloud API, Instagram or Messenger) as a fixed text, so they cost no AI. On the WhatsApp Cloud API the 24-hour window must still be open; otherwise the reminder is skipped and the appointment shows why. An appointment booked inside the reminder window gets no reminder, since the confirmation was just sent.

## For the team

The **Booking** tab lists the next 30 days of appointments, who booked each one (an agent or the team) and the reminder state. From there you can book from the free times, open the chat, and mark an appointment attended, no-show or cancelled. The team may book outside the published hours, but never beyond the capacity of a time.

## API

- `GET` / `PUT /api/clients/{id}/booking`: the settings.
- `GET /api/clients/{id}/booking/slots?date=YYYY-MM-DD&days=7`: free start times.
- `GET /api/clients/{id}/appointments?from=&to=&status=`: appointments.
- `POST /api/clients/{id}/appointments`, `PATCH` / `DELETE /api/clients/{id}/appointments/{appointment_id}`.
