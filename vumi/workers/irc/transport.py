from twisted.words.protocols import irc
from twisted.internet.defer import inlineCallbacks
from twisted.internet import protocol, reactor
from twisted.python import log
from vumi.service import Worker
from vumi.message import Message
from datetime import datetime
from vumi.webapp.api import utils
import time, json

class MessageLogger:
    """
    An independent logger class (because separation of application
    and protocol logic is a good thing).
    """
    def __init__(self, server, publisher):
        self.server = server
        self.publisher = publisher

    def log(self, **kwargs):
        """Write a message to the file."""
        timestamp = datetime.utcnow()
        
        payload = {
            "nickname": kwargs.get('nickname', 'system'),
            "server": self.server,
            "channel": kwargs.get('channel', 'unknown'),
            "message_type": kwargs.get('message_type', 'message'),
            "message_content": kwargs.get('msg', ''),
            "timestamp": timestamp.isoformat()
        }
        
        # self.publisher.publish_message(Message(
        #     recipient='ircarchive@appspot.com', message=json.dumps(payload)))
        utils.post_data_to_url('http://ircarchive.appspot.com/', 
                                json.dumps(payload), 'application/json')

class LogBot(irc.IRCClient):
    """A logging IRC bot."""
    nickname = 'twistedbot'
    
    def connectionMade(self):
        self.nickname = self.factory.nickname
        irc.IRCClient.connectionMade(self)
        self.logger = MessageLogger(self.factory.network, self.factory.publisher)
        self.logger.log(message_type='system', msg="[%s connected at %s]" % (self.nickname, 
                        time.asctime(datetime.utcnow().timetuple())))

    def connectionLost(self, reason):
        irc.IRCClient.connectionLost(self, reason)
        if hasattr(self, 'logger'):
            self.logger.log(message_type='system', msg="[%s disconnected at %s]" % (self.nickname, 
                        time.asctime(datetime.utcnow().timetuple())))

    # callbacks for events

    def signedOn(self):
        """Called when bot has succesfully signed on to server."""
        for channel in self.factory.channels:
            self.join(channel)

    def joined(self, channel):
        """This will get called when the bot joins the channel."""
        self.logger.log(message_type='system', msg="[%s has joined %s]" % (self.nickname, channel))

    def privmsg(self, user, channel, msg):
        """This will get called when the bot receives a message."""
        user = user.split('!', 1)[0]
        
        # Check to see if they're sending me a private message
        if channel == self.nickname:
            msg = "It isn't nice to whisper!  Play nice with the group."
            self.msg(user, msg)
            return
        else:
            self.logger.log(nickname=user, channel=channel, msg=msg)

    def action(self, user, channel, msg):
        """This will get called when the bot sees someone do an action."""
        user = user.split('!', 1)[0]
        self.logger.log(message_type='action', channel=channel, msg="* %s %s" % (user, msg))

    # irc callbacks

    def irc_NICK(self, prefix, params):
        """Called when an IRC user changes their nickname."""
        old_nick = prefix.split('!')[0]
        new_nick = params[0]
        self.logger.log(message_type='system', msg="%s is now known as %s" % (old_nick, new_nick))


    # For fun, override the method that determines how a nickname is changed on
    # collisions. The default method appends an underscore.
    def alterCollidedNick(self, nickname):
        """
        Generate an altered version of a nickname that caused a collision in an
        effort to create an unused related name for subsequent registration.
        """
        return nickname + '^'


class LogBotFactory(protocol.ReconnectingClientFactory):
    """A factory for LogBots.

    A new protocol instance will be created each time we connect to the server.
    """

    # the class of the protocol to build when new connection is made
    protocol = LogBot

    def __init__(self, network, nickname, channels, publisher):
        self.network = network
        self.nickname = nickname
        self.channels = channels
        self.publisher = publisher
        
    def buildProtocol(self, addr):
        self.resetDelay()
        p = self.protocol()
        p.factory = self
        return p

class IrcTransport(Worker):
    
    @inlineCallbacks
    def startWorker(self):
        network = self.config.get('network', 'irc.freenode.net')
        channels = self.config.get('channels', [])
        nickname = self.config.get('nickname', 'vumibot')
        port = self.config.get('port', 6667)
        self.publisher = yield self.publish_to('xmpp.outbound.gtalk.%s' % self.config.get('gtalk'))
        
        # create factory protocol and application
        f = LogBotFactory(network, nickname, channels, self.publisher)
        
        # connect factory to this host and port
        reactor.connectTCP(network, port, f)
    
    
    def consume_message(self, message):
        log.msg('Consumed Message with %s' % message.payload)
    
    @inlineCallbacks
    def stopWorker(self):
        yield None