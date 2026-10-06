package app.taxcopilot.forwarder;

import android.app.job.JobParameters;
import android.app.job.JobService;

/** Retries undelivered messages when the network is back (with exponential backoff). */
public class RetryService extends JobService {
    @Override
    public boolean onStartJob(final JobParameters params) {
        new Thread(new Runnable() {
            @Override
            public void run() {
                boolean done = Sender.flush(getApplicationContext());
                jobFinished(params, !done);  // not done -> reschedule with backoff
            }
        }).start();
        return true;
    }

    @Override
    public boolean onStopJob(JobParameters params) {
        return true;
    }
}
