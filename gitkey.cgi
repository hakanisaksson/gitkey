#!/usr/bin/perl

=pod

=head1 NAME

B<gitkey.cgi>

=head1 SYNOPSIS

gitkey.cgi [--help] [--generate]

=head1 OPTIONS

=over 10

=item B<--debug>

Show debug info.

=item B<--generate_authorized_keys>

Generate authorized keys

=back

=head1 DESCRIPTION

This is a CGI script and is ment to run from apache on a git-server.
It's enables users to submit their public sshkeys for access to the git repositories (assuming they are accessing the git repositories through a single user, usually the git user).
This script must be password protected by the webserver with at least basic auth (preferably with ssl and ldap), it will not work unless the username is defined in the environment variable $REMOTE_USER.
It is also advisable to set "LogLevel VERBOSE" in /etc/ssh/sshd_config to be able to match logins with public key signature.
The script can also run from the commandline with limited functionality (i.e. to generate ssh authorized_keys with the --generate_authorized_keys flag, or with the --debug flag).

This script is pepared for localization with Locale::Maketext::Simple
To localize run:
  xgettext.pl gitkey.cgi -P perl -v -v -v -g -o=gitkey.po
  msgfmt --check --statistics --verbose gitkey.po -o sv.mo

=head1 KNOWN ISSUES

NOTICE: You must install both Locale-Maketext-Lexicon and Locale-Maketext-Simple, or the .mo file will never be loaded, some distros (i.e. redhat) does not have proper dependencies on these packages).
Also older versions of Locale::Maketext::Lexicon are buggy and can't find the .mo files, this script works with the latest versions from CPAN which at the time of writing is Locale-Maketext-Lexicon-0.92 and Locale-Maketext-Simple-0.21.

=head1 EXAMPLES

gitkey.cgi --generate_authorized_keys
REMOTE_USER=someuser ./gitkey.cgi --debug

=head1 AUTHOR

hakan.isaksson@init.se

=head1 COPYRIGHT

Copyright (c) 2013 Hakan Isaksson.
This program is free software; you can redistribute it and/or modify it
under the same terms as Perl itself.

=cut

use strict;
use warnings;
use FindBin;
use Encode;
use Pod::Usage;
use Getopt::Long;
use File::Basename qw(basename);
use Data::Dumper;
use CGI qw(:standard :escapeHTML -nosticky);
use YAML::Any qw'DumpFile LoadFile';
use POSIX 'strftime';
use utf8;

use Locale::Maketext::Simple (
    Path   => '.',  ### Looks for .mo in the same dir as this script
    Decode => 1,
    Style  => 'gettext',
    );

binmode STDOUT, ':utf8';

#
# Globals
#
my $DEBUG = 0;  ### Debug mode
my $HTML = 1;   ### Print HTML

my $YAMLFILE = $FindBin::Bin."/".basename($FindBin::Script,".cgi").".yaml";

our %g = (
    SSHKEYS => "/git/pubkeys",                          ### path to store users public keys
    AUTHORIZED_KEYS => "/git/pubkeys/authorized_keys",  ### path to generated keyfile containing all keys
    MINKEYLENGHT => 200,                                ### Minimum key length allowed to upload
    KEEPDELETED => 1,                                   ### Keep deleted ssh-keys (for auditing purpose)
    MAXKEYS => 9,                                       ### Max keys one user can keep
    LANG => 'sv',                                       ### Localized language for Maketext
    );

#
# Env
#
my $CGI = defined $ENV{'GATEWAY_INTERFACE'};
my $MOD_PERL = defined $ENV{'MOD_PERL'};
my $REMOTE_USER = $ENV{'REMOTE_USER'};

$ENV{PATH}="/sbin:/bin:/usr/sbin:/usr/bin";
delete @ENV{qw(IFS CDPATH ENV BASH_ENV)};

#
# Html vars
#
our $nl ="\n";
$nl = "<br>\n" if $HTML;

our $q = new CGI;
our $base_url = $q->url();
our $base_uri = $q->url(-absolute => 1);


BEGIN {
        CGI->compile() if $ENV{'MOD_PERL'};
}

#sub __ { return @_ }  ### stub for gettext
sub __ { loc(@_) }  ### stub for maketext

#
# Print debug message
#
sub debug {
    my $msg = shift;
    print "[DEBUG] $msg".$nl if $DEBUG;
}

#
# Print error message and exit
#
sub error {
    my $msg = shift;
    $msg = "[ERROR] ".$msg; 
    $msg = f("bold","$msg") if $HTML;
    print $nl.$msg.$nl;
    exit(1);
}

#
# Print message with $nl as newline, or $end if 2nd argument is defined
#
sub msg {
    my $msg = shift;
    my $end = shift;
    defined $end ?  print $msg.$end : print $msg.$nl;
}

#
# Trim whitespace on $str
#
sub trim($) {
    my $str = shift;
    $str =~ s/^\s+//;
    $str =~ s/\s+$//;
    return $str;
}

#
# Untaint and check variable named $varname based on regex $patt
#
sub untaint {
    my $val = shift;
    my $patt = shift;
    my $varname = shift;
    
#    my $val = eval "return \$".$varname;
    return $val if ! defined $val;
    $varname = $val if ! defined $varname;
    $varname.="=$val";
    my $new = undef;
    $new = $1 if ( $val =~ /$patt/);
    error("Invalid characters in $varname") if defined $new and $new ne $val;
    return $new;
}

#
# Print environment vaiables as debug info
#
sub debug_env {
    my $arg = shift;
    $DEBUG=$arg if defined $arg;

    debug "base_url = $base_url";
    debug "base_uri = $base_uri";

    msg h("All parameters:",3);
    my %v = $q->Vars();
    debug "vars=".Dumper(\%v);

    msg h("All environment variables:",3);
    foreach my $key (sort(keys(%ENV))) {
	debug "$key = $ENV{$key}";
    }
}

#
#    Convert $msg to html headline if this is CGI
#
sub h {
    my $msg = shift;
    my $size = shift;
    return $msg if ! $HTML;
    return $q->h1($msg) if ! defined $size;
    return $q->h2($msg) if $size eq 2;
    return $q->h3($msg) if $size eq 3;
}

#
# Font manipulations on $msg, with css class
#
sub f {
    my $class = shift;
    my $msg = shift;
    return $msg if ! $HTML;
    $msg = "<font class=\"$class\">$msg</font>";
    return $msg;
}

# hrow($arg)
# Return array or arrayref as table row (<tr></tr>) formated string
#
sub hrow {
    my $arg = shift;
    my $str = "";
    my @row;

    if (ref($arg) eq "ARRAY") {
	@row = @{$arg};
    } else {
	@row = $arg;
    }
    if ($arg) {
	if ($HTML) {
	    $str=$q->start_Tr;
	    foreach my $col ( @row) {
		$str.=$q->start_td.$col.$q->end_td;
	    }
	    $str.=$q->end_Tr."\n";
	} else {
	    $str=$q->start_Tr if $HTML;
            foreach my $col ( @row) {
		$str.=$col."\t" if ! $HTML;
            }
	    $str.="\n" if ! $HTML;
	}
    } 

    return $str;
}

#    htable($arg)
#    Convert an array of arrays into html table 
#    or can print as plain text for shell output
#    Expects a hashref or arrayref as argument $arg
#    The hashref my contain options as well as the arraref data
#    any option starting with '-' is sent to CGI function $q->start_table
#    Can handle arbitrary columns, css class.
#    Return table as string or print while processing
#
sub htable {
    my $arg = shift;   ### hashref or arrayref
    my $ret = "";      ### table returned as string
    my %tableopts;     ### options sent to CGI->start_table
    my $columns = 0;   ### number of columns detected
    my $data;          ### the actual table data
    my $class;         ### optional div class
    debug "htable: \$arg = ".Dumper($arg);

    ### parse options
    if (ref($arg) eq "HASH") {
	foreach my $key (keys %{$arg}) {
	    debug "htable: \$arg->{$key} = ".$arg->{$key};
	    $tableopts{$key}=$arg->{$key} if $key =~ /^-/;
	    if ($key eq 'columns') { ### we have columns
		$columns = scalar( @{ $arg->{$key}  }); ### number of columns
	    }
            $class = $arg->{$key} if $key eq 'class';
	}
	$data = $arg->{'data'};
    }
    debug "htable: columns = $columns";

    ### assemble table 
    $data = $arg if ! defined $data;
    if (ref($data) eq "ARRAY") {
        $ret.= "<div class=\"$class\">\n" if defined $class and $HTML;
	$ret.= $q->start_table (\%tableopts)."\n" if $HTML;
	$ret.= hrow( $arg->{'columns'}  ) if $columns;
	foreach my $row (@{$data}) {
	    #if (ref($row) eq "ARRAY") {
		$ret.= hrow($row);
	    #} else { ### one column only
		#$ret.= hrow($row);
	    #}
	}
	$ret.= $q->end_table."\n" if $HTML;
        $ret.= "</div>\n" if defined $class and $HTML;
	return $ret;
    }  
    else {
	error("htable: invalid arg $arg");
    }
}

#
# Generate authorized_keys from all users stored public keys
#
sub generate_authorized_keys {
    debug "generate_authorized_keys";
    open(WF,">".$g{AUTHORIZED_KEYS}) or error("Can't write $g{AUTHORIZED_KEYS}: $!");
    my $numkeys=0;
    foreach my $sshkey (glob($g{SSHKEYS}."/*.pub")) {
        open(RF, "<$sshkey") or error("Can't open $sshkey: $!");
        my $keytext = do { local $/; <RF> };
        print WF $keytext;
        debug $sshkey;
        close(RF);
        $numkeys++;
    }
    close(WF);
    msg f("red",__("Generated %1",$g{AUTHORIZED_KEYS}));
}

#
# Check if $sshkey is valid with ssh-keygen and return info about the key as hash
#
sub check_sshkey {
    my $sshkey = shift;
    my %keyinfo;

    my $keygen = qx#ssh-keygen -l -f $sshkey#; chomp($keygen);
    if ( $? eq 0 ) {
        my ($bits,$id,$path) = split(/\s/,$keygen);
        $keyinfo{'bits'} = untaint($bits,'([\d]+)','bits');
        $keyinfo{'id'} = untaint($id,'([\w\:]+)','id');
        $keyinfo{'path'}= untaint($path,'([\w\/\.]+)','path');
    } else {
        $keyinfo{'bits'}=0;
        $keyinfo{'id'}='INVALID KEY!';
        $keyinfo{'path'}='';
    }
    $keyinfo{'basename'}=basename($sshkey);
    return %keyinfo;

}

#
# Print a list of the users stored sshkeys as html table
#
sub list_sshkeys {

    error("SSHKEYS directory $g{SSHKEYS} does not exist.") if ! -d $g{SSHKEYS};
    my $numkeys=0;
    my %table = ( -border => 1, topbgcolor => '#87cefa', );
    my @rows;
    foreach my $sshkey (glob($g{SSHKEYS}."/$REMOTE_USER*.pub")) {
	debug "Found sshkey = $sshkey";
        my $size = (stat($sshkey))[7]; ### size replaced by bits

        my %keyinfo = check_sshkey($sshkey);

	push(@rows,[ $sshkey, $keyinfo{id}, $keyinfo{bits}, 
                     "<a href=\"".$base_uri."?del=".$keyinfo{basename}."\" class=\"button\" >".__("Delete")."</a>" ]);
	$numkeys++;
    }
    $table{'data'}=\@rows;
    $table{'columns'}= [ __('ssh-key'),'id',__('bits'),'&nbsp;'];
    $table{'class'}='csstable';

    msg(h(__("You have the following ssh-keys"),2),'') if $numkeys;

    print htable(\%table) if $numkeys;
    return $numkeys;
}

#
# Form for uploading a public key
#
sub add_key {
    msg h(__("Upload a public ssh-key"),2),"\n";
    msg(__("A ssh-key can be created with 'ssh-keygen'."));
    print $q->start_form;
    print $q->textarea(
        -name  => 'keytext',
        -cols  => 80,
        -rows  => 10,
	),$nl;
    print $q->submit(
        -name     => 'add_key',
        -value    => __("Upload"),
        -class     => "button",
	);
    msg "&nbsp;&nbsp;&nbsp;".f("bold",__("OBS! Only upload the public key, not the private one."));
    print $q->end_form.$nl.$nl;
}

#
# Handle uploaded key from form submit
#
sub add_key_submit {
    my $addkey = shift;
    my $keytext = shift;

    debug "add_key_submit: key = $keytext";
    debug "add_key_submit: length = ".length($keytext);

    chomp($keytext); 
    $keytext =~ s/\r\n//g;
    $keytext = trim($keytext);
    $keytext = untaint($keytext,'(.*)','keytext');

    my $m = "Does not look like a valid ssh key";
    error("$m, key is too short.") if length($keytext) < $g{MINKEYLENGHT};
    error("$m") if  substr($keytext,0,4) ne "ssh-";

    error("Can't write to directory ".$g{SSHKEYS}) if ! -w $g{SSHKEYS};
    open(WF, ">$addkey") or error("Can't create $addkey");
    printf WF $keytext."\n";
    close(WF);

    my %keyinfo = check_sshkey($addkey);
    if ($keyinfo{bits} eq 0) {
        unlink $addkey;
        msg f("red","ERROR: $addkey not saved, $keyinfo{id}");
        #error("$addkey not saved, $keyinfo{id}");
    } else {
        msg f("red",__("Saved as %1",$addkey));
        generate_authorized_keys();
    }
}

#
# Handle request to delete key 
#
sub del_key_submit {
    my $delkey = shift;
    my $bkey = basename($delkey);
    $bkey = $1 if ($bkey =~ /([\w\.]+)/);
    error("Don't try it!") if $bkey ne $delkey;
    $delkey = $g{SSHKEYS}."/".$bkey;

    if ($g{KEEPDELETED}) {
        my $now = strftime "%Y%m%d%H%M", localtime;
        my $deleted =  $g{SSHKEYS}."/".basename($delkey,".pub").".deleted_".$now;
        rename $delkey, $deleted or error "Failed to rename $delkey to $deleted";
        msg f("red",__("Deleted key %1",$delkey));
    } else {
        if ( unlink $delkey ) {
            msg f("red",__("Deleted key %1",$delkey));
            generate_authorized_keys();
        } else {
            error("Failed to delete $delkey: $!");
        }
    }
}

#
# Print html page header
#
sub print_header {
    my $lang = 'en-US';
    $lang= 'sv-SE' if $g{'LANG'} eq 'sv';

    $g{'TITLE'} = sprintf("%s", __("SSH-KEY for GIT"));

    print $q->header(-type    => 'text/html',
		     -charset => 'utf-8'),
    $q->start_html(-title => $g{TITLE}, -lang => $lang),
    $q->Link({'rel'    => 'stylesheet',
                        'type'   => 'text/css',
                        'href'   => 'gitkey.css'})."\n",
    $q->h1($g{TITLE})."\n" if $HTML; 
}

#
# Return a sutable name for storing the users sshkey
#
sub find_keyname {
    my $username = shift;
    my $keyname = undef;
    for (my $i=0; $i< $g{MAXKEYS}; $i++) {
	$keyname = $g{SSHKEYS}."/".$username.$i.".pub";
	return $keyname if ! -e $keyname;
    }
    return $keyname;
}

#
# Get commandline params
#
sub parse_args {

    return if $CGI;
    my $GENKEY = 0;
    GetOptions (
        "debug" => \$DEBUG,
        "generate_authorized_keys" => sub { $GENKEY=1;$HTML=0;$nl="\n"; },
        ); 
    generate_authorized_keys(),exit if $GENKEY;
    pod2usage({ -verbose => 2}) if ! $DEBUG;

}

#
# Get POST or URL params
#
sub parse_params {
    my %vars = $q->Vars();
    debug "parse_args: vars=".Dumper(\%vars).$nl;

    foreach my $var (keys %vars) {
	
	if ($var eq "keytext") {
	    my $keyname=find_keyname($REMOTE_USER);
            add_key_submit ($keyname,$vars{$var});
	    
	}
	del_key_submit($vars{$var}) if $var eq "del";
        debug_env(1) if $var eq "debug"; ### undocumented debug
    }
}

#
# Check if user is authenticated
#
sub auth_user {
    if (defined $REMOTE_USER) {
        error("REMOTE_USER is empty") if $REMOTE_USER eq "";
        $REMOTE_USER = untaint($REMOTE_USER,'(\w+)','REMOTE_USER');
    } else {
        error(h(__("Not authenticated user, access denied.")));
    }
    debug "REMOTE_USER=$REMOTE_USER";
}

#
# Load or create config file if it does not exists, uses YAML
#
sub load_config {
    if ( -f "$YAMLFILE") {
        my $data = LoadFile( $YAMLFILE );
        %g = %{$data};
    } else {
        my $data = \%g;
        DumpFile( $YAMLFILE, $data );
    }
    loc_lang($g{'LANG'});  ### Yes I do not want the lang detected by locale, only text directed to the users should be translated, not system messages!

}
#
# Main
#
load_config();
parse_args();
print_header();

auth_user();

parse_params();

if (! list_sshkeys() ) {
    debug "No keys found for REMOTE_USER $REMOTE_USER";
    msg(h(__("You have no keys uploaded."),2),"\n");
} 
add_key();

msg __("gitkey by Håkan Isaksson, 2013");

END {
    print $q->end_html if $HTML and $CGI;
}
